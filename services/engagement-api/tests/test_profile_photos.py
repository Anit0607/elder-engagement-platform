import asyncio
import base64
import hashlib
import io
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.config import ConfigurationError
from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.profile_photos import (
    GooglePhotoStorage,
    PhotoUploadRequest,
    PostgresProfilePhotoService,
    UnconfiguredProfilePhotoService,
    verify_profile_photo_schema,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
OWNER = uuid4()


def request(content_type="image/png", data=b"synthetic"):
    return PhotoUploadRequest(
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.mark.parametrize("content_type", ["text/plain", "image/gif"])
def test_upload_request_rejects_unsupported_types(content_type):
    with pytest.raises(ValidationError):
        request(content_type)


def test_upload_request_rejects_oversize_and_unknown_fields():
    valid = {"contentType": "image/png", "sizeBytes": 1, "sha256": "a" * 64}
    with pytest.raises(ValidationError):
        PhotoUploadRequest.model_validate({**valid, "sizeBytes": 5_242_881})
    with pytest.raises(ValidationError):
        PhotoUploadRequest.model_validate({**valid, "fileName": "personal.png"})


def test_photo_switch_requires_profiles(settings):
    with pytest.raises(ValueError):
        type(settings).model_validate({**settings.model_dump(), "profile_photo_enabled": True})


class Connection:
    def __init__(self, row=None, exists=True):
        self.row, self.exists, self.executed = row, exists, []

    async def fetchval(self, *_args):
        return self.exists

    async def fetchrow(self, *_args):
        return self.row

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Authorization:
    def __init__(self, connection):
        self.connection = connection

    def _proof(self, _token):
        return OWNER, uuid4(), "member", None

    @asynccontextmanager
    async def transaction(self, *_args, **_kwargs):
        yield self.connection, Mock(user_id=OWNER)


def test_start_authorises_only_private_fixed_shape_upload():
    connection = Connection()
    storage = Mock(
        upload_url=AsyncMock(
            return_value=("https://storage.googleapis.com/private?signed", {"Content-Type": "image/png"})
        )
    )
    service = PostgresProfilePhotoService(Authorization(connection), Mock(), storage, now=lambda: NOW)
    result = asyncio.run(service.start("token", request(), "synthetic-trace"))
    inserted = connection.executed[0][1]
    assert result.method == "PUT" and result.expires_at == NOW + timedelta(minutes=5)
    assert str(OWNER) in inserted[2] and inserted[2].startswith("profile-photo-quarantine/")
    assert "token" not in str(result.upload_url) and len(connection.executed) == 1


def test_start_requires_existing_profile():
    service = PostgresProfilePhotoService(
        Authorization(Connection(exists=False)), Mock(), Mock(), now=lambda: NOW
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.start("token", request(), "trace"))
    assert error.value.status == 404


def intent(*, completed=False, expired=False):
    return {
        "content_type": "image/png",
        "size_bytes": 9,
        "sha256": "a" * 64,
        "quarantine_object_key": "profile-photo-quarantine/source.png",
        "approved_object_key": "profile-photos/done.png" if completed else None,
        "completed_at": NOW if completed else None,
        "expires_at": NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=5),
        "previous_photo_object_key": None,
    }


def test_complete_validates_promotes_attaches_and_audits():
    connection = Connection(row=intent())
    storage = Mock(validate_and_promote=AsyncMock())
    profile = Mock(_read=AsyncMock(return_value={"photoUrl": "https://short-lived"}))
    service = PostgresProfilePhotoService(Authorization(connection), profile, storage, now=lambda: NOW)
    result = asyncio.run(service.complete("token", uuid4(), "synthetic-trace"))
    destination = storage.validate_and_promote.call_args.args[1]
    assert destination.startswith(f"profile-photos/{OWNER}/")
    assert result["photoUrl"] == "https://short-lived"
    assert any("profile_photo_uploads" in call[0] for call in connection.executed)
    assert any("profile.photo.updated" in call[0] for call in connection.executed)


def test_complete_replaces_photo_and_treats_old_photo_cleanup_as_best_effort():
    row = intent()
    row["previous_photo_object_key"] = "profile-photos/old.webp"
    connection = Connection(row=row)
    storage = Mock(
        validate_and_promote=AsyncMock(),
        delete_approved=AsyncMock(
            side_effect=MemberSessionFailure(status=503, code="DEPENDENCY_UNAVAILABLE", title="temporary")
        ),
    )
    profile = Mock(_read=AsyncMock(return_value={"photoUrl": "https://short-lived"}))
    service = PostgresProfilePhotoService(Authorization(connection), profile, storage, now=lambda: NOW)
    result = asyncio.run(service.complete("token", uuid4(), "synthetic-trace"))
    assert result["photoUrl"] == "https://short-lived"
    storage.delete_approved.assert_awaited_once_with("profile-photos/old.webp")


@pytest.mark.parametrize(
    "row,status", [(None, 404), (intent(completed=True), 409), (intent(expired=True), 409)]
)
def test_complete_rejects_missing_used_or_expired_intent(row, status):
    service = PostgresProfilePhotoService(Authorization(Connection(row=row)), Mock(), Mock(), now=lambda: NOW)
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.complete("token", uuid4(), "trace"))
    assert error.value.status == status


class Credentials:
    token = "synthetic-runtime-token"  # noqa: S105 -- synthetic response fixture

    def refresh(self, _request):
        return None


class Response:
    def __init__(self, status, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload or {}, content

    def json(self):
        return self._payload


def test_signed_upload_url_contains_no_runtime_token_and_binds_headers():
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response(200, {"signedBlob": base64.b64encode(b"synthetic-signature").decode()})

    storage = GooglePhotoStorage(
        "synthetic-project",
        "signer@synthetic-project.iam.gserviceaccount.com",
        "private-uploads",
        "private-approved",
        now=lambda: NOW,
        credentials=Credentials(),
        requester=requester,
    )
    url, headers = asyncio.run(storage.upload_url("profile-photo-quarantine/photo.png", request(), 300))
    assert "runtime-token" not in url and "X-Goog-Signature=" in url
    assert "content-length%3Bcontent-type%3Bhost" in url
    assert headers == {"Content-Length": "9", "Content-Type": "image/png"}
    assert calls[0][0] == "POST" and calls[0][1].endswith(":signBlob")


def png_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(stream, format="PNG")
    return stream.getvalue()


def test_storage_validates_hash_sanitises_image_then_deletes():
    data = png_bytes()
    destination = "profile-photos/destination.webp"
    responses = iter(
        [
            Response(200, {"contentType": "image/png", "size": str(len(data)), "generation": "7"}),
            Response(200, content=data),
            Response(200, {"name": destination}),
            Response(204),
        ]
    )
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return next(responses)

    storage = GooglePhotoStorage(
        "synthetic-project",
        "signer@synthetic-project.iam.gserviceaccount.com",
        "private-uploads",
        "private-approved",
        credentials=Credentials(),
        requester=requester,
    )
    asyncio.run(
        storage.validate_and_promote(
            "profile-photo-quarantine/source.png",
            destination,
            request(data=data),
        )
    )
    assert [call[0] for call in calls] == ["GET", "GET", "POST", "DELETE"]
    assert calls[2][2]["params"] == {
        "uploadType": "media",
        "name": destination,
        "ifGenerationMatch": "0",
    }
    assert calls[2][2]["headers"]["Content-Type"] == "image/webp"
    with Image.open(io.BytesIO(calls[2][2]["data"])) as approved:
        assert approved.format == "WEBP" and approved.getexif() == {}
    assert calls[3][2]["params"] == {"ifGenerationMatch": "7"}


def test_storage_retry_accepts_only_identical_existing_approved_object():
    data = png_bytes()
    expected_clean = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(expected_clean, format="WEBP", quality=85, method=6)
    responses = iter(
        [
            Response(200, {"contentType": "image/png", "size": str(len(data)), "generation": "7"}),
            Response(200, content=data),
            Response(412),
            Response(200, content=expected_clean.getvalue()),
            Response(500),
        ]
    )
    storage = GooglePhotoStorage(
        "synthetic-project",
        "signer@synthetic-project.iam.gserviceaccount.com",
        "private-uploads",
        "private-approved",
        credentials=Credentials(),
        requester=lambda *_args, **_kwargs: next(responses),
    )
    asyncio.run(
        storage.validate_and_promote(
            "profile-photo-quarantine/source.png",
            "profile-photos/destination.webp",
            request(data=data),
        )
    )


def test_storage_retry_rejects_different_existing_approved_object():
    data = png_bytes()
    responses = iter(
        [
            Response(200, {"contentType": "image/png", "size": str(len(data)), "generation": "7"}),
            Response(200, content=data),
            Response(412),
            Response(200, content=b"different"),
        ]
    )
    storage = GooglePhotoStorage(
        "synthetic-project",
        "signer@synthetic-project.iam.gserviceaccount.com",
        "private-uploads",
        "private-approved",
        credentials=Credentials(),
        requester=lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(
            storage.validate_and_promote(
                "profile-photo-quarantine/source.png",
                "profile-photos/destination.webp",
                request(data=data),
            )
        )
    assert error.value.status == 503


def test_storage_rejects_invalid_image_before_copy():
    data = b"not-an-image"
    responses = iter(
        [
            Response(200, {"contentType": "image/png", "size": str(len(data)), "generation": "7"}),
            Response(200, content=data),
        ]
    )
    storage = GooglePhotoStorage(
        "synthetic-project",
        "signer@synthetic-project.iam.gserviceaccount.com",
        "private-uploads",
        "private-approved",
        credentials=Credentials(),
        requester=lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(
            storage.validate_and_promote(
                "profile-photo-quarantine/source.png",
                "profile-photos/destination.png",
                request(data=data),
            )
        )
    assert error.value.status == 409


def test_schema_and_unconfigured_service_fail_closed():
    pool = Mock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=Connection(exists=False))
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ConfigurationError):
        asyncio.run(verify_profile_photo_schema(pool))
    service = UnconfiguredProfilePhotoService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(service.start("token", request(), "trace"))
    with pytest.raises(MemberSessionFailure):
        asyncio.run(service.complete("token", uuid4(), "trace"))


def test_http_photo_routes_validate_and_hide_service_failures(settings):
    service = Mock()
    service.start = AsyncMock(
        return_value={
            "uploadId": str(uuid4()),
            "uploadUrl": "https://storage.googleapis.com/private?signed=true",
            "method": "PUT",
            "requiredHeaders": {"Content-Type": "image/png", "Content-Length": "9"},
            "expiresAt": (NOW + timedelta(minutes=5)).isoformat(),
        }
    )
    service.complete = AsyncMock(
        side_effect=MemberSessionFailure(status=409, code="CONFLICT", title="Synthetic conflict")
    )
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, profile_photo_service=service)) as client:
        response = client.post(
            "/v1/me/profile/photo-upload",
            headers=headers,
            json={"contentType": "image/png", "sizeBytes": 9, "sha256": "a" * 64},
        )
        assert response.status_code == 201 and response.json()["method"] == "PUT"
        assert client.post("/v1/me/profile/photo-upload", headers=headers, json={}).status_code == 400
        response = client.post(f"/v1/me/profile/photo-upload/{uuid4()}/complete", headers=headers)
        assert response.status_code == 409 and response.json()["code"] == "CONFLICT"
        assert "synthetic-proof" not in response.text
