import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ConfigurationError, Settings
from app.events import EventCreate, PostgresEventService, UnconfiguredEventService, verify_event_schema
from app.main import create_app
from app.member_auth import MemberSessionFailure

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
ADMIN = uuid4()
MEMBER = uuid4()
CIRCLE = uuid4()
EVENT = uuid4()


def event_request(audience="all_members", circles=None, **changes):
    payload = {
        "title": "Synthetic music gathering",
        "description": "Fictional event for automated checks",
        "startsAt": (NOW + timedelta(days=2)).isoformat(),
        "endsAt": (NOW + timedelta(days=2, hours=1)).isoformat(),
        "audience": audience,
        "circleIds": circles or [],
        "reminderMinutesBefore": [1440, 60],
    }
    payload.update(changes)
    return EventCreate.model_validate(payload)


def event_row(identifier=EVENT, starts_at=None):
    return {
        "id": identifier,
        "title": "Synthetic music gathering",
        "description": None,
        "starts_at": starts_at or NOW + timedelta(days=2),
        "ends_at": None,
        "created_at": NOW,
        "all_members": False,
        "circle_ids": [CIRCLE],
        "reminder_minutes_before": [1440, 60],
    }


class Connection:
    def __init__(self, rows=(), ready=True):
        self.rows, self.ready, self.executed = list(rows), ready, []

    async def fetch(self, query, *_args):
        if "FROM engagement_app.circles" in query:
            return [{"id": CIRCLE}]
        return self.rows

    async def fetchval(self, *_args):
        return self.ready

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Authorization:
    def __init__(self, connection, user=ADMIN, role="administrator"):
        self.connection, self.user, self.role = connection, user, role
        self.permissions = []

    def _proof(self, _token):
        return self.user, uuid4(), self.role, None

    @asynccontextmanager
    async def transaction(self, _token, permission, **_kwargs):
        self.permissions.append(permission.value)
        yield self.connection, Mock(user_id=self.user, role=self.role)


@pytest.mark.parametrize(
    "changes",
    [
        {"startsAt": "2026-09-18T10:00:00"},
        {"endsAt": "2026-09-18T09:00:00Z"},
        {"audience": "all_members", "circleIds": [str(CIRCLE)]},
        {"audience": "circles", "circleIds": []},
        {"reminderMinutesBefore": [60, 60]},
        {"reminderMinutesBefore": [4]},
        {"reminderMinutesBefore": [10081]},
        {"reminderMinutesBefore": ["60"]},
    ],
)
def test_event_request_rejects_ambiguous_or_unsafe_rules(changes):
    with pytest.raises(ValidationError):
        event_request(**changes)


def test_administrator_creates_circle_event_with_reminders_and_audit():
    connection = Connection()
    authorization = Authorization(connection)
    result = asyncio.run(
        PostgresEventService(authorization, now=lambda: NOW).create(
            "proof", event_request("circles", [CIRCLE]), "trace"
        )
    )
    assert result.audience == "circles" and result.circle_ids == [CIRCLE]
    assert result.reminder_minutes_before == [1440, 60]
    assert result.join_kind == "information_only"
    assert authorization.permissions == ["manage-events"]
    statements = "\n".join(query for query, _ in connection.executed)
    assert "INSERT INTO engagement_app.events" in statements
    assert "event_audiences" in statements
    assert statements.count("event_reminder_rules") == 2
    assert "event.created" in statements


def test_event_create_refuses_past_time_or_inactive_circle():
    service = PostgresEventService(Authorization(Connection()), now=lambda: NOW)
    with pytest.raises(MemberSessionFailure) as past:
        asyncio.run(
            service.create(
                "proof",
                event_request(startsAt=(NOW - timedelta(minutes=1)).isoformat(), endsAt=None),
                "trace",
            )
        )
    assert past.value.code == "VALIDATION_FAILED"

    connection = Connection()

    async def no_circles(_query, *_args):
        return []

    connection.fetch = no_circles
    with pytest.raises(MemberSessionFailure) as inactive:
        asyncio.run(
            PostgresEventService(Authorization(connection), now=lambda: NOW).create(
                "proof", event_request("circles", [CIRCLE]), "trace"
            )
        )
    assert inactive.value.status == 409


def test_member_event_list_is_bounded_cursor_paginated_and_period_bound():
    second = uuid4()
    rows = [event_row(), event_row(second, NOW + timedelta(days=3))]
    authorization = Authorization(Connection(rows), MEMBER, "member")
    service = PostgresEventService(authorization, now=lambda: NOW)
    page = asyncio.run(service.list_visible("proof", "upcoming", 1, None))
    assert [item.id for item in page.items] == [EVENT]
    assert page.next_cursor
    assert service._decode_cursor("upcoming", page.next_cursor) == (
        NOW + timedelta(days=2),
        EVENT,
    )
    with pytest.raises(MemberSessionFailure):
        service._decode_cursor("past", page.next_cursor)
    assert authorization.permissions == ["view-events"]


def test_schema_configuration_unconfigured_and_http_boundaries(settings):
    pool = Mock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=Connection(ready=False))
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ConfigurationError):
        asyncio.run(verify_event_schema(pool))
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "event_service_enabled": True})

    disabled = UnconfiguredEventService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.create("proof", event_request(), "trace"))
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.list_visible("proof", "upcoming", 20, None))

    service = Mock(
        create=AsyncMock(
            return_value={
                "id": str(EVENT),
                "title": "Synthetic music gathering",
                "description": None,
                "startsAt": (NOW + timedelta(days=2)).isoformat(),
                "endsAt": None,
                "audience": "all_members",
                "circleIds": [],
                "reminderMinutesBefore": [60],
                "joinKind": "information_only",
                "createdAt": NOW.isoformat(),
            }
        ),
        list_visible=AsyncMock(return_value={"items": [], "nextCursor": None}),
    )
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, event_service=service)) as client:
        response = client.post(
            "/v1/admin/events",
            headers=headers,
            json=event_request().model_dump(by_alias=True, mode="json"),
        )
        assert response.status_code == 201
        assert client.get("/v1/events?period=upcoming&limit=20", headers=headers).status_code == 200
        assert client.get("/v1/events?period=unknown", headers=headers).status_code == 400
        assert client.get("/v1/events?limit=51", headers=headers).status_code == 400
