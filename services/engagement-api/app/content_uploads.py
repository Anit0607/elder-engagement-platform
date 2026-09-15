"""Private Contributor content uploads awaiting Administrator moderation."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure

RIGHTS_STATEMENT_VERSION = "2026-09-16"
CONTENT_TYPES = {
    "video/mp4": ("video", "mp4", 262_144_000),
    "audio/mpeg": ("audio", "mp3", 52_428_800),
    "audio/mp4": ("audio", "m4a", 52_428_800),
    "audio/x-m4a": ("audio", "m4a", 52_428_800),
    "application/pdf": ("pdf", "pdf", 26_214_400),
}


def unavailable():
    return MemberSessionFailure(
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        title="Content upload service is temporarily unavailable",
    )


class ContentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    language: Literal["en", "bn", "hi"]
    content_type: Literal[
        "video/mp4", "audio/mpeg", "audio/mp4", "audio/x-m4a", "application/pdf"
    ] = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes", ge=1, le=262_144_000)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    rights_confirmed: Literal[True] = Field(alias="rightsConfirmed")

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Content title is too short")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("sha256")
    @classmethod
    def canonical_hash(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def check_type_size_limit(self):
        if self.size_bytes > CONTENT_TYPES[self.content_type][2]:
            raise ValueError("File exceeds the approved limit for its type")
        return self


class ContentUploadAuthorisation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    upload_id: UUID = Field(alias="uploadId")
    upload_url: AnyUrl = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    required_headers: dict[str, str] = Field(alias="requiredHeaders")
    expires_at: datetime = Field(alias="expiresAt")


class ContentUploadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    upload_id: UUID = Field(alias="uploadId")
    status: Literal["pending"]
    kind: Literal["video", "audio", "pdf"]


class UnconfiguredContentUploadService:
    async def start(self, token, request, trace_id):
        raise unavailable()

    async def complete(self, token, upload_id, trace_id):
        raise unavailable()


async def verify_content_upload_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        ready = await connection.fetchval(
            """SELECT to_regclass('engagement_app.content_uploads') IS NOT NULL"""
        )
    if ready is not True:
        raise ConfigurationError("The Contributor content-upload database migration is required")


def _matches_file_signature(content_type: str, leading_bytes: bytes) -> bool:
    if content_type == "application/pdf":
        return leading_bytes.startswith(b"%PDF-")
    if content_type == "audio/mpeg":
        return leading_bytes.startswith(b"ID3") or (
            len(leading_bytes) >= 2
            and leading_bytes[0] == 0xFF
            and leading_bytes[1] & 0xE0 == 0xE0
        )
    return len(leading_bytes) >= 12 and leading_bytes[4:8] == b"ftyp"


class GoogleContentStorage:
    """Use the existing signed-upload storage adapter and validate by streaming."""

    def __init__(self, signed_storage):
        self._storage = signed_storage

    async def upload_url(self, object_key, request, expires_seconds):
        signed_headers = {
            "content-length": str(request.size_bytes),
            "content-type": request.content_type,
            "x-goog-if-generation-match": "0",
        }
        url = await self._storage._signed_url(
            "PUT",
            self._storage.uploads_bucket,
            object_key,
            expires_seconds,
            signed_headers,
        )
        return url, {
            "Content-Length": str(request.size_bytes),
            "Content-Type": request.content_type,
            "x-goog-if-generation-match": "0",
        }

    async def validate(self, object_key: str, expected: ContentUploadRequest) -> int:
        return await asyncio.to_thread(self._validate_sync, object_key, expected)

    def _validate_sync(self, object_key: str, expected: ContentUploadRequest) -> int:
        token = self._storage._access_token()
        bucket = quote(self._storage.uploads_bucket, safe="")
        encoded_key = quote(object_key, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{encoded_key}"
        headers = {"Authorization": f"Bearer {token}"}
        metadata_response = self._storage._request("GET", url, headers=headers)
        if metadata_response.status_code == 404:
            raise MemberSessionFailure(
                status=404, code="NOT_FOUND", title="Uploaded content was not found"
            )
        if metadata_response.status_code != 200:
            raise unavailable()
        try:
            metadata = metadata_response.json()
            size = int(metadata.get("size", -1))
            generation = str(metadata.get("generation", ""))
        except (ValueError, TypeError):
            raise unavailable() from None
        if (
            metadata.get("contentType") != expected.content_type
            or size != expected.size_bytes
            or not re.fullmatch(r"[1-9][0-9]*", generation)
        ):
            raise MemberSessionFailure(
                status=409,
                code="UPLOAD_MISMATCH",
                title="Uploaded content does not match its authorisation",
            )
        media = self._storage._request(
            "GET", url, headers=headers, params={"alt": "media"}, stream=True
        )
        if media.status_code != 200:
            raise unavailable()
        digest = hashlib.sha256()
        leading = bytearray()
        received = 0
        try:
            for chunk in media.iter_content(chunk_size=1_048_576):
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected.size_bytes:
                    raise ValueError("Stored object exceeds its declared size")
                if len(leading) < 32:
                    leading.extend(chunk[: 32 - len(leading)])
                digest.update(chunk)
        except (OSError, ValueError):
            raise MemberSessionFailure(
                status=409,
                code="UPLOAD_MISMATCH",
                title="Uploaded content does not match its authorisation",
            ) from None
        if (
            received != expected.size_bytes
            or digest.hexdigest() != expected.sha256
            or not _matches_file_signature(expected.content_type, bytes(leading))
        ):
            raise MemberSessionFailure(
                status=409,
                code="UPLOAD_MISMATCH",
                title="Uploaded content does not match its authorisation",
            )
        return int(generation)


class PostgresContentUploadService:
    def __init__(self, authorization, storage, *, expires_seconds=300, now=lambda: datetime.now(UTC)):
        self.authorization = authorization
        self.storage = storage
        self.expires_seconds = expires_seconds
        self.now = now

    async def start(self, token, request: ContentUploadRequest, trace_id):
        owner = self.authorization._proof(token)[0]
        content_item_id, upload_id = uuid4(), uuid4()
        kind, extension, _ = CONTENT_TYPES[request.content_type]
        object_key = f"content-quarantine/{owner}/{content_item_id}/{upload_id}.{extension}"
        now = self.now().astimezone(UTC)
        expires_at = now + timedelta(seconds=self.expires_seconds)
        async with self.authorization.transaction(
            token, Permission.UPLOAD_CONTENT, target=owner
        ) as (connection, _):
            await connection.execute(
                """INSERT INTO engagement_app.content_items
                   (id,contributor_id,kind,title,description,language,status,
                    rights_statement_version,rights_confirmed_at,created_at,updated_at)
                   VALUES($1,$2,$3,$4,$5,$6,'draft',$7,$8,$8,$8)""",
                content_item_id,
                owner,
                kind,
                request.title,
                request.description,
                request.language,
                RIGHTS_STATEMENT_VERSION,
                now,
            )
            await connection.execute(
                """INSERT INTO engagement_app.content_uploads
                   (id,content_item_id,contributor_id,quarantine_object_key,
                    content_type,size_bytes,sha256,expires_at,created_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                upload_id,
                content_item_id,
                owner,
                object_key,
                request.content_type,
                request.size_bytes,
                request.sha256,
                expires_at,
                now,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'content.upload.authorised','content_item',$2,$3,
                     jsonb_build_object('rightsStatementVersion',$4::text))""",
                owner,
                str(content_item_id),
                trace_id,
                RIGHTS_STATEMENT_VERSION,
            )
        url, headers = await self.storage.upload_url(object_key, request, self.expires_seconds)
        return ContentUploadAuthorisation(
            content_item_id=content_item_id,
            upload_id=upload_id,
            upload_url=url,
            required_headers=headers,
            expires_at=expires_at,
        )

    async def complete(self, token, upload_id: UUID, trace_id):
        owner = self.authorization._proof(token)[0]
        async with self.authorization.transaction(
            token, Permission.UPLOAD_CONTENT, target=owner
        ) as (connection, _):
            row = await connection.fetchrow(
                """SELECT upload.*, item.kind::text
                   FROM engagement_app.content_uploads AS upload
                   JOIN engagement_app.content_items AS item ON item.id=upload.content_item_id
                   WHERE upload.id=$1 AND upload.contributor_id=$2""",
                upload_id,
                owner,
            )
            if row is None:
                raise MemberSessionFailure(
                    status=404, code="NOT_FOUND", title="Content upload was not found"
                )
            if row["status"] != "authorised":
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="Content upload is already final"
                )
            now = self.now().astimezone(UTC)
            if row["expires_at"] <= now:
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="Content upload has expired"
                )
            expected = ContentUploadRequest(
                title="Stored upload",
                language="en",
                contentType=row["content_type"],
                sizeBytes=row["size_bytes"],
                sha256=row["sha256"],
                rightsConfirmed=True,
            )
        try:
            generation = await self.storage.validate(row["quarantine_object_key"], expected)
        except MemberSessionFailure as error:
            if error.status in {404, 409}:
                async with self.authorization.transaction(
                    token, Permission.UPLOAD_CONTENT, target=owner
                ) as (connection, _):
                    await connection.execute(
                        """WITH rejected AS (
                             UPDATE engagement_app.content_uploads
                             SET status='rejected',completed_at=$3
                             WHERE id=$1 AND contributor_id=$2 AND status='authorised'
                             RETURNING content_item_id
                           )
                           UPDATE engagement_app.content_items SET status='rejected',updated_at=$3
                           WHERE id=(SELECT content_item_id FROM rejected)""",
                        upload_id,
                        owner,
                        now,
                    )
            raise

        async with self.authorization.transaction(
            token, Permission.UPLOAD_CONTENT, target=owner
        ) as (connection, _):
            current = await connection.fetchrow(
                """SELECT upload.*, item.kind::text
                   FROM engagement_app.content_uploads AS upload
                   JOIN engagement_app.content_items AS item ON item.id=upload.content_item_id
                   WHERE upload.id=$1 AND upload.contributor_id=$2 FOR UPDATE OF upload,item""",
                upload_id,
                owner,
            )
            if current is None:
                raise MemberSessionFailure(
                    status=404, code="NOT_FOUND", title="Content upload was not found"
                )
            if current["status"] != "authorised":
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="Content upload is already final"
                )
            await connection.execute(
                """INSERT INTO engagement_app.content_assets
                   (content_item_id,object_key,detected_media_type,declared_media_type,
                    size_bytes,sha256,quarantined,scan_status)
                   VALUES($1,$2,$3,$3,$4,$5,true,'pending')""",
                current["content_item_id"],
                current["quarantine_object_key"],
                current["content_type"],
                current["size_bytes"],
                current["sha256"],
            )
            await connection.execute(
                """UPDATE engagement_app.content_uploads SET
                   status='completed',storage_generation=$2,completed_at=$3 WHERE id=$1""",
                upload_id,
                generation,
                now,
            )
            await connection.execute(
                """UPDATE engagement_app.content_items SET
                   status='pending',updated_at=$2 WHERE id=$1""",
                current["content_item_id"],
                now,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'content.upload.completed','content_item',$2,$3,'{}'::jsonb)""",
                owner,
                str(current["content_item_id"]),
                trace_id,
            )
        return ContentUploadReceipt(
            content_item_id=current["content_item_id"],
            upload_id=upload_id,
            status="pending",
            kind=current["kind"],
        )
