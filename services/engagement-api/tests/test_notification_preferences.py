from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authorization import Permission, Principal
from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.notification_preferences import (
    NotificationPreferences,
    NotificationPreferencesUpdate,
    delivery_is_allowed,
)
from app.postgres_notification_preferences import PostgresNotificationPreferencesService


def preferences(**overrides):
    values = {
        "eventReminders": True,
        "contentUpdates": True,
        "deliveryWindow": {"enabled": False, "timeZone": "Asia/Kolkata"},
        "updatedAt": datetime.now(UTC),
    }
    values.update(overrides)
    return NotificationPreferences.model_validate(values)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"eventReminders": True, "contentUpdates": True},
        {
            "eventReminders": "true",
            "contentUpdates": True,
            "deliveryWindow": {"enabled": False, "timeZone": "UTC"},
        },
        {
            "eventReminders": True,
            "contentUpdates": True,
            "deliveryWindow": {"enabled": True, "timeZone": "UTC"},
        },
    ],
)
def test_preference_update_is_complete_and_strict(value):
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdate.model_validate(value)


def test_delivery_policy_respects_category_disabled_window_and_midnight():
    moment = datetime(2026, 9, 15, 18, 0, tzinfo=UTC)  # 23:30 in Kolkata
    assert delivery_is_allowed(preferences(), "event", moment)
    assert not delivery_is_allowed(preferences(eventReminders=False), "event", moment)
    overnight = preferences(
        deliveryWindow={
            "enabled": True,
            "timeZone": "Asia/Kolkata",
            "startLocalTime": "22:00",
            "endLocalTime": "06:00",
        }
    )
    assert delivery_is_allowed(overnight, "content", moment)
    assert not delivery_is_allowed(overnight, "content", moment + timedelta(hours=8))
    with pytest.raises(ValueError):
        delivery_is_allowed(preferences(), "event", datetime(2026, 9, 15))
    with pytest.raises(ValueError):
        delivery_is_allowed(preferences(), "unknown", moment)


class Authorization:
    def __init__(self, *, existing=True):
        self.owner = uuid4()
        self.row = {
            "account_updated_at": datetime.now(UTC),
            "enabled": False,
            "window_start": None,
            "window_end": None,
            "time_zone": "Asia/Kolkata",
            "push_events": True,
            "push_content": False,
            "updated_at": datetime.now(UTC) if existing else None,
        }
        self.fetchval = AsyncMock(return_value=True)
        self.execute = AsyncMock()
        self.committed = False

    def _proof(self, token):
        return self.owner, uuid4(), "member", None

    @asynccontextmanager
    async def transaction(self, proof_value, permission, *, target):
        assert proof_value == "synthetic-proof"
        assert permission == Permission.OWN_NOTIFICATIONS and target == self.owner
        yield self, Principal(self.owner, uuid4(), "member")
        self.committed = True

    async def fetchrow(self, query, *args):
        return self.row


@pytest.mark.anyio
async def test_missing_preferences_return_safe_defaults_without_writing():
    auth = Authorization(existing=False)
    result = await PostgresNotificationPreferencesService(auth).get("synthetic-proof")
    assert result.event_reminders and result.content_updates
    assert not result.delivery_window.enabled
    auth.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_replace_saves_complete_preferences_and_minimal_audit():
    auth = Authorization()
    auth.row.update(push_events=False, push_content=True)
    update = NotificationPreferencesUpdate(
        eventReminders=False,
        contentUpdates=True,
        deliveryWindow={
            "enabled": True,
            "timeZone": "Asia/Kolkata",
            "startLocalTime": "22:00",
            "endLocalTime": "06:00",
        },
    )
    result = await PostgresNotificationPreferencesService(auth).replace(
        "synthetic-proof", update, "synthetic-trace"
    )
    assert auth.committed and not result.event_reminders and result.content_updates
    assert auth.execute.await_count == 2
    stored = auth.execute.await_args_list[0].args
    assert stored[1] == auth.owner and stored[-2:] == (False, True)
    assert "Asia/Kolkata" not in auth.execute.await_args_list[1].args


@pytest.mark.anyio
async def test_invalid_database_timezone_does_not_write():
    auth = Authorization()
    auth.fetchval.return_value = False
    update = NotificationPreferencesUpdate(
        eventReminders=True,
        contentUpdates=True,
        deliveryWindow={"enabled": False, "timeZone": "Synthetic/Unknown"},
    )
    with pytest.raises(MemberSessionFailure) as error:
        await PostgresNotificationPreferencesService(auth).replace(
            "synthetic-proof", update, "synthetic-trace"
        )
    assert error.value.status == 400 and not auth.committed
    auth.execute.assert_not_awaited()


def test_http_preferences_and_disabled_default(settings):
    auth = Authorization()
    service = PostgresNotificationPreferencesService(auth)
    headers = {"Authorization": "Bearer synthetic-proof"}
    payload = {
        "eventReminders": True,
        "contentUpdates": False,
        "deliveryWindow": {"enabled": False, "timeZone": "Asia/Kolkata"},
    }
    with TestClient(create_app(settings, notification_preferences_service=service)) as client:
        assert client.get("/v1/me/notification-preferences", headers=headers).status_code == 200
        assert client.put("/v1/me/notification-preferences", headers=headers, json=payload).status_code == 200
        assert (
            client.put(
                "/v1/me/notification-preferences", headers=headers, json={**payload, "unknown": True}
            ).status_code
            == 400
        )
        assert client.get("/v1/me/notification-preferences").status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/me/notification-preferences", headers=headers).status_code == 503
