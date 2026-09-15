import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ConfigurationError, Settings
from app.content_feed import (
    ContentPublicationRequest,
    GoogleContentFeedStorage,
    PostgresContentFeedService,
    UnconfiguredContentFeedService,
    verify_content_feed_schema,
)
from app.main import create_app
from app.member_auth import MemberSessionFailure

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
CONTENT = uuid4()
ASSET = uuid4()
ADMIN = uuid4()
MEMBER = uuid4()
CIRCLE = uuid4()


def publication(audience="all_members", circles=None):
    return ContentPublicationRequest.model_validate(
        {"audience": audience, "circleIds": circles or []}
    )


def approved_row(**changes):
    row = {
        "status": "approved",
        "published_at": None,
        "asset_id": ASSET,
        "object_key": f"content-quarantine/{uuid4()}/{CONTENT}/{ASSET}.mp4",
        "declared_media_type": "video/mp4",
        "size_bytes": 1234,
        "sha256": "a" * 64,
        "scan_status": "clean",
        "quarantined": True,
    }
    row.update(changes)
    return row


def feed_row(identifier=CONTENT, published=NOW):
    return {
        "id": identifier,
        "kind": "video",
        "title": "Synthetic circle video",
        "description": None,
        "language": "en",
        "published_at": published,
        "display_name": "Fictional Contributor",
    }


class Connection:
    def __init__(self, *, row=None, rows=()):
        self.row = row
        self.rows = list(rows)
        self.executed = []

    async def fetchrow(self, *_args):
        return self.row

    async def fetch(self, query, *_args):
        if "FROM engagement_app.circles" in query:
            return [{"id": CIRCLE}]
        return self.rows

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class Authorization:
    def __init__(self, connection, user=ADMIN, role="administrator"):
        self.connection = connection
        self.user = user
        self.role = role
        self.permissions = []

    def _proof(self, _token):
        return self.user, uuid4(), self.role, None

    @asynccontextmanager
    async def transaction(self, _token, permission, **_kwargs):
        self.permissions.append(permission.value)
        yield self.connection, Mock(user_id=self.user, role=self.role)


@pytest.mark.parametrize(
    "payload",
    [
        {"audience": "all_members", "circleIds": [str(CIRCLE)]},
        {"audience": "circles", "circleIds": []},
        {"audience": "circles", "circleIds": [str(CIRCLE), str(CIRCLE)]},
        {"audience": "public", "circleIds": []},
    ],
)
def test_publication_request_rejects_ambiguous_audiences(payload):
    with pytest.raises(ValidationError):
        ContentPublicationRequest.model_validate(payload)


def test_administrator_publication_promotes_media_and_records_audience_and_audit():
    connection = Connection(row=approved_row())
    storage = Mock(promote=AsyncMock(return_value=f"content/{CONTENT}/{ASSET}.mp4"))
    authorization = Authorization(connection)
    result = asyncio.run(
        PostgresContentFeedService(authorization, storage, now=lambda: NOW).publish(
            "proof", CONTENT, publication("circles", [CIRCLE]), "trace"
        )
    )
    assert result.audience == "circles" and result.circle_ids == [CIRCLE]
    assert authorization.permissions == ["manage-content-publication"]
    storage.promote.assert_awaited_once()
    statements = "\n".join(query for query, _ in connection.executed)
    assert "content_audiences" in statements
    assert "quarantined=false" in statements
    assert "content.published" in statements


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending"},
        {"published_at": NOW},
        {"scan_status": "failed"},
        {"quarantined": False},
    ],
)
def test_publication_refuses_unready_or_already_published_content(changes):
    service = PostgresContentFeedService(
        Authorization(Connection(row=approved_row(**changes))), Mock()
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.publish("proof", CONTENT, publication(), "trace"))
    assert error.value.status == 409


def test_circle_publication_refuses_an_unknown_or_inactive_circle():
    connection = Connection(row=approved_row())

    async def missing(_query, *_args):
        return []

    connection.fetch = missing
    service = PostgresContentFeedService(Authorization(connection), Mock())
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(
            service.publish("proof", CONTENT, publication("circles", [CIRCLE]), "trace")
        )
    assert error.value.status == 409


def test_member_feed_is_bounded_cursor_paginated_and_role_checked():
    second = uuid4()
    rows = [feed_row(), feed_row(second)]
    authorization = Authorization(Connection(rows=rows), MEMBER, "member")
    service = PostgresContentFeedService(authorization, Mock())
    first = asyncio.run(service.feed("proof", 1, None))
    assert [item.content_item_id for item in first.items] == [CONTENT]
    assert first.next_cursor
    decoded = service._decode_cursor(first.next_cursor)
    assert decoded == (NOW, CONTENT)
    assert authorization.permissions == ["view-content-feed"]
    with pytest.raises(MemberSessionFailure) as error:
        service._decode_cursor("not-valid")
    assert error.value.code == "INVALID_CURSOR"


def test_member_media_rechecks_visibility_and_returns_a_short_lived_url():
    connection = Connection(
        row={
            "object_key": f"content/{CONTENT}/{ASSET}.mp4",
            "declared_media_type": "video/mp4",
        }
    )
    storage = Mock(member_url=AsyncMock(return_value="https://storage.googleapis.com/private"))
    result = asyncio.run(
        PostgresContentFeedService(
            Authorization(connection, MEMBER, "member"), storage, now=lambda: NOW
        ).media("proof", CONTENT)
    )
    assert result.content_type == "video/mp4"
    assert int((result.expires_at - NOW).total_seconds()) == 300
    storage.member_url.assert_awaited_once()


def test_storage_paths_are_separated_between_quarantine_and_approved_content():
    source = f"content-quarantine/{uuid4()}/{CONTENT}/{ASSET}.pdf"
    assert GoogleContentFeedStorage.destination_key(CONTENT, ASSET, source) == (
        f"content/{CONTENT}/{ASSET}.pdf"
    )
    with pytest.raises(MemberSessionFailure):
        GoogleContentFeedStorage.destination_key(CONTENT, ASSET, "../unsafe.pdf")


def test_storage_signs_only_approved_content_paths():
    signed = Mock(
        approved_bucket="private-approved",
        _signed_url=AsyncMock(return_value="https://storage.googleapis.com/private"),
    )
    storage = GoogleContentFeedStorage(signed)
    key = f"content/{CONTENT}/{ASSET}.mp3"
    assert asyncio.run(storage.member_url(key, 300)).startswith("https://")
    signed._signed_url.assert_awaited_once_with("GET", "private-approved", key, 300)
    with pytest.raises(MemberSessionFailure):
        asyncio.run(storage.member_url("content-quarantine/unsafe.mp3", 300))


def test_storage_promotes_the_exact_reviewed_object_and_is_retry_safe():
    row = approved_row()
    source = Response(
        200,
        {
            "generation": "123",
            "size": str(row["size_bytes"]),
            "contentType": row["declared_media_type"],
        },
    )
    signed = Mock(
        uploads_bucket="private-quarantine",
        approved_bucket="private-approved",
        _access_token=Mock(return_value="synthetic-token"),
        _request=Mock(side_effect=[source, Response(200), Response(204)]),
    )
    destination = asyncio.run(GoogleContentFeedStorage(signed).promote(CONTENT, ASSET, row))
    assert destination == f"content/{CONTENT}/{ASSET}.mp4"
    copy_call = signed._request.call_args_list[1]
    assert "/copyTo/" in copy_call.args[1]
    assert copy_call.kwargs["params"] == {
        "ifGenerationMatch": "0",
        "ifSourceGenerationMatch": "123",
    }
    assert copy_call.kwargs["json"]["metadata"]["ee-sha256"] == "a" * 64

    existing = Response(
        200,
        {
            "size": str(row["size_bytes"]),
            "contentType": row["declared_media_type"],
            "metadata": {"ee-sha256": row["sha256"]},
        },
    )
    retry = Mock(
        uploads_bucket="private-quarantine",
        approved_bucket="private-approved",
        _access_token=Mock(return_value="synthetic-token"),
        _request=Mock(side_effect=[Response(404), existing]),
    )
    assert asyncio.run(GoogleContentFeedStorage(retry).promote(CONTENT, ASSET, row)) == destination


def test_storage_refuses_a_changed_or_missing_reviewed_object():
    row = approved_row()
    changed = Response(
        200,
        {
            "generation": "123",
            "size": str(row["size_bytes"] + 1),
            "contentType": row["declared_media_type"],
        },
    )
    signed = Mock(
        uploads_bucket="private-quarantine",
        approved_bucket="private-approved",
        _access_token=Mock(return_value="synthetic-token"),
        _request=Mock(return_value=changed),
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(GoogleContentFeedStorage(signed).promote(CONTENT, ASSET, row))
    assert error.value.status == 409


def test_missing_member_media_and_all_unconfigured_operations_fail_closed():
    service = PostgresContentFeedService(
        Authorization(Connection(row=None), MEMBER, "member"), Mock()
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.media("proof", CONTENT))
    assert error.value.status == 404

    disabled = UnconfiguredContentFeedService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.publish("proof", CONTENT, publication(), "trace"))
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.media("proof", CONTENT))


def test_schema_configuration_and_http_boundary(settings):
    pool = Mock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=Connection(rows=[]))
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ConfigurationError):
        asyncio.run(verify_content_feed_schema(pool))
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "content_feed_enabled": True})

    service = Mock(
        publish=AsyncMock(
            return_value={
                "contentItemId": str(CONTENT),
                "audience": "all_members",
                "circleIds": [],
                "publishedAt": NOW.isoformat(),
            }
        ),
        feed=AsyncMock(
            return_value={
                "items": [
                    {
                        "contentItemId": str(CONTENT),
                        "kind": "video",
                        "title": "Synthetic circle video",
                        "description": None,
                        "language": "en",
                        "contributorDisplayName": "Fictional Contributor",
                        "publishedAt": NOW.isoformat(),
                    }
                ],
                "nextCursor": None,
            }
        ),
        media=AsyncMock(
            return_value={
                "contentItemId": str(CONTENT),
                "mediaUrl": "https://storage.googleapis.com/private",
                "contentType": "video/mp4",
                "expiresAt": NOW.isoformat(),
            }
        ),
    )
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, content_feed_service=service)) as client:
        assert client.post(
            f"/v1/admin/content/{CONTENT}/publication",
            headers=headers,
            json={"audience": "all_members", "circleIds": []},
        ).status_code == 200
        assert client.get("/v1/feed?limit=20", headers=headers).status_code == 200
        assert client.get(
            f"/v1/feed/{CONTENT}/media", headers=headers
        ).status_code == 200
        assert client.get("/v1/feed?limit=51", headers=headers).status_code == 400

    disabled = UnconfiguredContentFeedService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(disabled.feed("proof", 20, None))
