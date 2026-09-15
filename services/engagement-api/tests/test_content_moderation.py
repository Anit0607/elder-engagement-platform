import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ConfigurationError, Settings
from app.content_moderation import (
    GoogleModerationPreviewStorage,
    ModerationDecisionRequest,
    PostgresContentModerationService,
    UnconfiguredContentModerationService,
    verify_content_moderation_schema,
)
from app.main import create_app
from app.member_auth import MemberSessionFailure

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
CONTENT = uuid4()
ADMIN = uuid4()
CONTRIBUTOR = uuid4()


def decision(outcome="approved", reason="approved", note=None):
    return ModerationDecisionRequest.model_validate(
        {"outcome": outcome, "reasonCode": reason, "note": note}
    )


@pytest.mark.parametrize(
    "outcome,reason,note",
    [
        ("rejected", "copyright_permission", None),
        ("rejected", "unsafe_inappropriate", None),
        ("rejected", "misleading", None),
        ("rejected", "poor_quality", None),
        ("rejected", "duplicate", None),
        ("rejected", "other", " Clear explanation "),
        ("approved", "approved", None),
    ],
)
def test_decision_accepts_only_the_approved_reason_catalogue(outcome, reason, note):
    result = decision(outcome, reason, note)
    assert result.note == (note.strip() if note else None)


@pytest.mark.parametrize(
    "outcome,reason,note",
    [
        ("approved", "poor_quality", None),
        ("rejected", "approved", None),
        ("rejected", "other", None),
        ("rejected", "other", "   "),
    ],
)
def test_decision_rejects_inconsistent_or_unexplained_choices(outcome, reason, note):
    with pytest.raises(ValidationError):
        decision(outcome, reason, note)


class Connection:
    def __init__(self, *, rows=(), row=None):
        self.rows, self.row, self.executed = rows, row, []

    async def fetch(self, *_args):
        return self.rows

    async def fetchrow(self, *_args):
        return self.row

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Authorization:
    def __init__(self, connection):
        self.connection, self.permissions = connection, []

    @asynccontextmanager
    async def transaction(self, _token, permission, **_kwargs):
        self.permissions.append(permission.value)
        yield self.connection, Mock(user_id=ADMIN, role="administrator")


def queue_row():
    return {
        "id": CONTENT,
        "contributor_id": CONTRIBUTOR,
        "display_name": "Fictional Contributor",
        "kind": "video",
        "title": "Synthetic upload",
        "description": None,
        "language": "en",
        "declared_media_type": "video/mp4",
        "size_bytes": 1234,
        "scan_status": "clean",
        "rights_confirmed_at": NOW,
        "created_at": NOW,
    }


def test_queue_returns_private_pending_metadata_for_administrator():
    connection = Connection(rows=[queue_row()])
    auth = Authorization(connection)
    result = asyncio.run(PostgresContentModerationService(auth, Mock()).queue("proof"))
    assert result[0].content_item_id == CONTENT
    assert result[0].contributor_display_name == "Fictional Contributor"
    assert auth.permissions == ["view-content-moderation"]


def test_preview_is_short_lived_and_rejects_unsafe_object_paths():
    key = f"content-quarantine/{uuid4()}/{uuid4()}/{uuid4()}.pdf"
    connection = Connection(row={"object_key": key})
    storage = Mock(preview_url=AsyncMock(return_value="https://storage.googleapis.com/private"))
    result = asyncio.run(
        PostgresContentModerationService(
            Authorization(connection), storage, now=lambda: NOW
        ).preview("proof", CONTENT)
    )
    assert result.expires_at == NOW + timedelta(seconds=120)
    storage.preview_url.assert_awaited_once_with(key, 120)

    signed = Mock(uploads_bucket="private", _signed_url=AsyncMock())
    with pytest.raises(MemberSessionFailure):
        asyncio.run(GoogleModerationPreviewStorage(signed).preview_url("../unsafe.pdf", 120))


def test_decision_is_final_audited_and_does_not_publish():
    connection = Connection(
        row={"status": "pending", "contributor_id": CONTRIBUTOR, "scan_status": "clean"}
    )
    service = PostgresContentModerationService(
        Authorization(connection), Mock(), now=lambda: NOW
    )
    result = asyncio.run(
        service.decide(
            "proof", CONTENT, decision("rejected", "other", "Synthetic check"), "trace"
        )
    )
    assert result.status == "rejected" and result.published is False
    assert any("moderation_decisions" in query for query, _ in connection.executed)
    assert any("content.moderation.decided" in query for query, _ in connection.executed)
    assert not any("published" in query.lower() for query, _ in connection.executed)


@pytest.mark.parametrize(
    "row,outcome,status",
    [
        (None, "approved", 404),
        ({"status": "approved", "contributor_id": CONTRIBUTOR, "scan_status": "clean"}, "approved", 409),
        ({"status": "pending", "contributor_id": CONTRIBUTOR, "scan_status": "failed"}, "approved", 409),
        ({"status": "pending", "contributor_id": CONTRIBUTOR, "scan_status": "rejected"}, "approved", 409),
        ({"status": "pending", "contributor_id": ADMIN, "scan_status": "clean"}, "approved", 403),
    ],
)
def test_decision_refuses_missing_repeated_or_failed_content(row, outcome, status):
    service = PostgresContentModerationService(Authorization(Connection(row=row)), Mock())
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.decide("proof", CONTENT, decision(outcome), "trace"))
    assert error.value.status == status


def test_schema_configuration_and_http_boundary(settings):
    pool = Mock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=Connection(rows=[]))
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ConfigurationError):
        asyncio.run(verify_content_moderation_schema(pool))

    with pytest.raises(ValueError):
        Settings.model_validate(
            {**settings.model_dump(), "content_moderation_enabled": True}
        )

    service = Mock(
        queue=AsyncMock(return_value=[PostgresContentModerationService._item(queue_row())]),
        preview=AsyncMock(
            return_value={
                "contentItemId": str(CONTENT),
                "previewUrl": "https://storage.googleapis.com/private",
                "expiresAt": NOW.isoformat(),
            }
        ),
        decide=AsyncMock(
            return_value={
                "contentItemId": str(CONTENT),
                "status": "approved",
                "reasonCode": "approved",
                "note": None,
                "decidedAt": NOW.isoformat(),
                "published": False,
            }
        ),
    )
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, content_moderation_service=service)) as client:
        assert client.get("/v1/admin/content-moderation", headers=headers).status_code == 200
        assert client.get(
            f"/v1/admin/content-moderation/{CONTENT}/preview", headers=headers
        ).status_code == 200
        assert client.post(
            f"/v1/admin/content-moderation/{CONTENT}/decision",
            headers=headers,
            json={"outcome": "approved", "reasonCode": "approved"},
        ).json()["published"] is False
        assert client.post(
            f"/v1/admin/content-moderation/{CONTENT}/decision",
            headers=headers,
            json={"outcome": "rejected", "reasonCode": "other"},
        ).status_code == 400

    disabled = UnconfiguredContentModerationService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.queue("proof"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/admin/content-moderation", headers=headers).status_code == 503
