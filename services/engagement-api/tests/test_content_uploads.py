import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ConfigurationError
from app.content_uploads import (
    ContentUploadRequest,
    GoogleContentStorage,
    PostgresContentUploadService,
    UnconfiguredContentUploadService,
    _matches_file_signature,
    verify_content_upload_schema,
)
from app.main import create_app
from app.member_auth import MemberSessionFailure

NOW = datetime(2026, 9, 16, tzinfo=UTC)
OWNER = uuid4()


def upload_request(content_type="application/pdf", data=b"%PDF-1.7 synthetic"):
    return ContentUploadRequest.model_validate(
        {
            "title": "Synthetic activity guide",
            "description": "Fictional content",
            "language": "en",
            "contentType": content_type,
            "sizeBytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "rightsConfirmed": True,
        }
    )


@pytest.mark.parametrize(
    "content_type,size",
    [
        ("video/mp4", 262_144_001),
        ("audio/mpeg", 52_428_801),
        ("audio/mp4", 52_428_801),
        ("application/pdf", 26_214_401),
    ],
)
def test_upload_request_enforces_per_type_limits(content_type, size):
    values = upload_request().model_dump(by_alias=True)
    values.update(contentType=content_type, sizeBytes=size)
    with pytest.raises(ValidationError):
        ContentUploadRequest.model_validate(values)


def test_upload_request_requires_true_rights_and_known_type():
    values = upload_request().model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        ContentUploadRequest.model_validate({**values, "rightsConfirmed": False})
    with pytest.raises(ValidationError):
        ContentUploadRequest.model_validate({**values, "contentType": "text/plain"})
    with pytest.raises(ValidationError):
        ContentUploadRequest.model_validate({**values, "fileName": "private.pdf"})


def test_content_upload_switch_requires_staff_runtime(settings):
    with pytest.raises(ValueError):
        type(settings).model_validate({**settings.model_dump(), "content_upload_enabled": True})


@pytest.mark.parametrize(
    "content_type,data,accepted",
    [
        ("application/pdf", b"%PDF-1.7", True),
        ("audio/mpeg", b"ID3synthetic", True),
        ("audio/mpeg", bytes([0xFF, 0xFB, 0x00]), True),
        ("video/mp4", b"\x00\x00\x00\x18ftypisom", True),
        ("audio/mp4", b"\x00\x00\x00\x18ftypM4A ", True),
        ("application/pdf", b"not-a-pdf", False),
    ],
)
def test_file_signature_checks(content_type, data, accepted):
    assert _matches_file_signature(content_type, data) is accepted


class Connection:
    def __init__(self, row=None, ready=True):
        self.row, self.ready, self.executed = row, ready, []

    async def fetchval(self, *_args):
        return self.ready

    async def fetchrow(self, *_args):
        return self.row

    async def execute(self, query, *args):
        self.executed.append((query, args))


class Authorization:
    def __init__(self, connection):
        self.connection = connection

    def _proof(self, _token):
        return OWNER, uuid4(), "contributor", None

    @asynccontextmanager
    async def transaction(self, *_args, **_kwargs):
        yield self.connection, Mock(user_id=OWNER, role="contributor")


def test_start_records_rights_private_intent_and_audit():
    connection = Connection()
    storage = Mock(
        upload_url=AsyncMock(
            return_value=(
                "https://storage.googleapis.com/private?signed=true",
                {"Content-Type": "application/pdf", "Content-Length": "18"},
            )
        )
    )
    service = PostgresContentUploadService(
        Authorization(connection), storage, now=lambda: NOW
    )
    result = asyncio.run(service.start("proof", upload_request(), "synthetic-trace"))
    assert result.method == "PUT" and result.expires_at == NOW + timedelta(minutes=5)
    assert len(connection.executed) == 3
    assert "content_items" in connection.executed[0][0]
    assert "content-quarantine" in connection.executed[1][1][3]
    assert "content.upload.authorised" in connection.executed[2][0]
    assert "$4::text" in connection.executed[2][0]


def test_content_upload_authorisation_prevents_object_replacement():
    signed = Mock(
        uploads_bucket="private-uploads",
        _signed_url=AsyncMock(return_value="https://storage.googleapis.com/private?signed=true"),
    )
    storage = GoogleContentStorage(signed)
    url, headers = asyncio.run(storage.upload_url("content-quarantine/item.pdf", upload_request(), 300))
    assert url.startswith("https://storage.googleapis.com/")
    assert headers["x-goog-if-generation-match"] == "0"
    assert signed._signed_url.await_args.args[-1]["x-goog-if-generation-match"] == "0"


def intent(*, status="authorised", expired=False):
    return {
        "id": uuid4(),
        "content_item_id": uuid4(),
        "contributor_id": OWNER,
        "quarantine_object_key": "content-quarantine/synthetic/item.pdf",
        "content_type": "application/pdf",
        "size_bytes": 18,
        "sha256": "a" * 64,
        "status": status,
        "expires_at": NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=5),
        "kind": "pdf",
    }


def test_complete_stream_validation_records_pending_asset_and_audit():
    connection = Connection(row=intent())
    storage = Mock(validate=AsyncMock(return_value=73))
    service = PostgresContentUploadService(
        Authorization(connection), storage, now=lambda: NOW
    )
    receipt = asyncio.run(service.complete("proof", uuid4(), "synthetic-trace"))
    assert receipt.status == "pending" and receipt.kind == "pdf"
    assert any("content_assets" in query for query, _ in connection.executed)
    assert any("status='pending'" in query for query, _ in connection.executed)
    assert any("content.upload.completed" in query for query, _ in connection.executed)


def test_invalid_file_is_rejected_and_never_recorded_as_pending():
    connection = Connection(row=intent())
    mismatch = MemberSessionFailure(status=409, code="UPLOAD_MISMATCH", title="Mismatch")
    service = PostgresContentUploadService(
        Authorization(connection), Mock(validate=AsyncMock(side_effect=mismatch)), now=lambda: NOW
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.complete("proof", uuid4(), "trace"))
    assert error.value.code == "UPLOAD_MISMATCH"
    assert any("status='rejected'" in query for query, _ in connection.executed)
    assert not any("content_assets" in query for query, _ in connection.executed)


@pytest.mark.parametrize(
    "row,status",
    [(None, 404), (intent(status="completed"), 409), (intent(expired=True), 409)],
)
def test_complete_rejects_missing_final_or_expired_upload(row, status):
    service = PostgresContentUploadService(
        Authorization(Connection(row=row)), Mock(), now=lambda: NOW
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(service.complete("proof", uuid4(), "trace"))
    assert error.value.status == status


class Response:
    def __init__(self, status, payload=None, chunks=()):
        self.status_code, self._payload, self._chunks = status, payload or {}, chunks

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks


class SignedStorage:
    uploads_bucket = "private-uploads"

    def __init__(self, responses):
        self.responses = iter(responses)

    def _access_token(self):
        return "synthetic-token"  # noqa: S105 -- non-working test fixture

    def _request(self, *_args, **_kwargs):
        return next(self.responses)


def test_storage_streams_and_validates_pdf_without_promoting_it():
    data = b"%PDF-1.7 synthetic"
    storage = GoogleContentStorage(
        SignedStorage(
            [
                Response(
                    200,
                    {"contentType": "application/pdf", "size": str(len(data)), "generation": "7"},
                ),
                Response(200, chunks=(data[:5], data[5:])),
            ]
        )
    )
    assert asyncio.run(storage.validate("content-quarantine/item.pdf", upload_request(data=data))) == 7


@pytest.mark.parametrize(
    "metadata,chunks",
    [
        ({"contentType": "text/plain", "size": "18", "generation": "7"}, (b"x" * 18,)),
        ({"contentType": "application/pdf", "size": "18", "generation": "7"}, (b"not a valid pdf!!!",)),
    ],
)
def test_storage_rejects_metadata_or_file_mismatch(metadata, chunks):
    storage = GoogleContentStorage(
        SignedStorage([Response(200, metadata), Response(200, chunks=chunks)])
    )
    with pytest.raises(MemberSessionFailure) as error:
        asyncio.run(storage.validate("content-quarantine/item.pdf", upload_request()))
    assert error.value.status == 409


def test_schema_and_unconfigured_service_fail_closed():
    pool = Mock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=Connection(ready=False))
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ConfigurationError):
        asyncio.run(verify_content_upload_schema(pool))
    service = UnconfiguredContentUploadService()
    with pytest.raises(MemberSessionFailure):
        asyncio.run(service.start("proof", upload_request(), "trace"))
    with pytest.raises(MemberSessionFailure):
        asyncio.run(service.complete("proof", uuid4(), "trace"))


def test_http_content_upload_routes_validate_and_hide_failures(settings):
    service = Mock()
    service.start = AsyncMock(
        return_value={
            "contentItemId": str(uuid4()),
            "uploadId": str(uuid4()),
            "uploadUrl": "https://storage.googleapis.com/private?signed=true",
            "method": "PUT",
            "requiredHeaders": {"Content-Type": "application/pdf", "Content-Length": "18"},
            "expiresAt": (NOW + timedelta(minutes=5)).isoformat(),
        }
    )
    service.complete = AsyncMock(
        side_effect=MemberSessionFailure(status=409, code="UPLOAD_MISMATCH", title="Mismatch")
    )
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, content_upload_service=service)) as client:
        response = client.post(
            "/v1/contributor/content-uploads",
            headers=headers,
            json=upload_request().model_dump(by_alias=True),
        )
        assert response.status_code == 201 and response.json()["method"] == "PUT"
        assert client.post(
            "/v1/contributor/content-uploads", headers=headers, json={}
        ).status_code == 400
        response = client.post(
            f"/v1/contributor/content-uploads/{uuid4()}/complete", headers=headers
        )
        assert response.status_code == 409 and response.json()["code"] == "UPLOAD_MISMATCH"
        assert "synthetic-proof" not in response.text
