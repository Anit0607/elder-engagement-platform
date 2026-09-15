"""Private profile-photo upload authorisation, validation and attachment."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import warnings
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

import google.auth
import google.auth.transport.requests
import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure

PHOTO_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
MAX_PHOTO_BYTES = 5_242_880
MAX_PHOTO_PIXELS = 40_000_000


def unavailable():
    return MemberSessionFailure(
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        title="Profile photo service is temporarily unavailable",
    )


class PhotoUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    content_type: Literal["image/jpeg", "image/png", "image/webp"] = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes", ge=1, le=MAX_PHOTO_BYTES)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("sha256")
    @classmethod
    def canonical_hash(cls, value):
        return value.lower()


class UploadAuthorisation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    upload_id: UUID = Field(alias="uploadId")
    upload_url: AnyUrl = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    required_headers: dict[str, str] = Field(alias="requiredHeaders")
    expires_at: datetime = Field(alias="expiresAt")


class UnconfiguredProfilePhotoService:
    async def start(self, token, request, trace_id):
        raise unavailable()

    async def complete(self, token, upload_id, trace_id):
        raise unavailable()


async def verify_profile_photo_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        ready = await connection.fetchval(
            """SELECT to_regclass('engagement_app.profile_photo_uploads') IS NOT NULL"""
        )
    if ready is not True:
        raise ConfigurationError("The profile-photo database migration is required")


class GooglePhotoStorage:
    def __init__(
        self,
        project,
        signer,
        uploads_bucket,
        approved_bucket,
        *,
        now=lambda: datetime.now(UTC),
        credentials=None,
        requester=requests.request,
    ):
        self.project = project
        self.signer = signer
        self.uploads_bucket = uploads_bucket
        self.approved_bucket = approved_bucket
        self.now = now
        if credentials is None:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.credentials = credentials
        self.requester = requester

    def _access_token(self):
        self.credentials.refresh(google.auth.transport.requests.Request())
        if not self.credentials.token:
            raise unavailable()
        return self.credentials.token

    def _request(self, method, url, **kwargs):
        try:
            response = self.requester(method, url, timeout=30, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise unavailable() from exc
        return response

    async def _signed_url(self, method, bucket, object_key, expires, headers=None):
        return await asyncio.to_thread(
            self._signed_url_sync, method, bucket, object_key, expires, headers or {}
        )

    def _signed_url_sync(self, method, bucket, object_key, expires, headers):
        now = self.now().astimezone(UTC)
        date = now.strftime("%Y%m%d")
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        scope = f"{date}/auto/storage/goog4_request"
        canonical_headers = {
            "host": "storage.googleapis.com",
            **{k.lower(): str(v) for k, v in headers.items()},
        }
        signed_headers = ";".join(sorted(canonical_headers))
        query = {
            "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
            "X-Goog-Credential": f"{self.signer}/{scope}",
            "X-Goog-Date": timestamp,
            "X-Goog-Expires": str(expires),
            "X-Goog-SignedHeaders": signed_headers,
        }
        canonical_query = urlencode(sorted(query.items()), quote_via=quote, safe="")
        canonical_uri = f"/{quote(bucket, safe='')}/{quote(object_key, safe='/~')}"
        header_text = "".join(
            f"{name}:{canonical_headers[name].strip()}\n" for name in sorted(canonical_headers)
        )
        canonical_request = "\n".join(
            [method, canonical_uri, canonical_query, header_text, signed_headers, "UNSIGNED-PAYLOAD"]
        )
        string_to_sign = "\n".join(
            [
                "GOOG4-RSA-SHA256",
                timestamp,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        token = self._access_token()
        signer_name = quote(self.signer, safe="")
        response = self._request(
            "POST",
            f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{signer_name}:signBlob",
            headers={"Authorization": f"Bearer {token}"},
            json={"payload": base64.b64encode(string_to_sign.encode()).decode()},
        )
        try:
            signature = base64.b64decode(response.json()["signedBlob"]).hex()
        except (KeyError, ValueError, TypeError) as exc:
            raise unavailable() from exc
        if response.status_code != 200 or not signature:
            raise unavailable()
        return f"https://storage.googleapis.com{canonical_uri}?{canonical_query}&X-Goog-Signature={signature}"

    async def upload_url(self, object_key, request, expires_seconds):
        headers = {"content-length": str(request.size_bytes), "content-type": request.content_type}
        return await self._signed_url("PUT", self.uploads_bucket, object_key, expires_seconds, headers), {
            "Content-Length": str(request.size_bytes),
            "Content-Type": request.content_type,
        }

    async def view_url(self, object_key):
        return await self._signed_url("GET", self.approved_bucket, object_key, 300)

    async def validate_and_promote(self, source_key, destination_key, expected):
        return await asyncio.to_thread(self._validate_and_promote_sync, source_key, destination_key, expected)

    async def delete_approved(self, object_key):
        return await asyncio.to_thread(self._delete_approved_sync, object_key)

    def _delete_approved_sync(self, object_key):
        token = self._access_token()
        bucket = quote(self.approved_bucket, safe="")
        encoded_key = quote(object_key, safe="")
        response = self._request(
            "DELETE",
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{encoded_key}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code not in {204, 404}:
            raise unavailable()

    def _validate_and_promote_sync(self, source_key, destination_key, expected):
        token = self._access_token()
        encoded_source = quote(source_key, safe="")
        encoded_bucket = quote(self.uploads_bucket, safe="")
        source_url = f"https://storage.googleapis.com/storage/v1/b/{encoded_bucket}/o/{encoded_source}"
        headers = {"Authorization": f"Bearer {token}"}
        metadata_response = self._request("GET", source_url, headers=headers)
        if metadata_response.status_code == 404:
            raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Uploaded photo was not found")
        if metadata_response.status_code != 200:
            raise unavailable()
        try:
            metadata = metadata_response.json()
        except (ValueError, TypeError) as exc:
            raise unavailable() from exc
        try:
            metadata_size = int(metadata.get("size", -1))
        except (TypeError, ValueError):
            metadata_size = -1
        if metadata.get("contentType") != expected.content_type or metadata_size != expected.size_bytes:
            raise MemberSessionFailure(
                status=409, code="CONFLICT", title="Uploaded photo does not match its authorisation"
            )
        media = self._request("GET", source_url, headers=headers, params={"alt": "media"})
        if media.status_code != 200 or len(media.content) != expected.size_bytes:
            raise unavailable()
        if hashlib.sha256(media.content).hexdigest() != expected.sha256:
            raise MemberSessionFailure(
                status=409, code="CONFLICT", title="Uploaded photo does not match its authorisation"
            )
        try:
            Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(media.content)) as image:
                    image.verify()
                    if image.format != PHOTO_TYPES[expected.content_type]:
                        raise ValueError("Image format differs from declared type")
                with Image.open(io.BytesIO(media.content)) as image:
                    clean = ImageOps.exif_transpose(image)
                    clean.thumbnail((2048, 2048))
                    clean = clean.convert("RGBA" if "A" in clean.getbands() else "RGB")
                    sanitized = io.BytesIO()
                    clean.save(sanitized, format="WEBP", quality=85, method=6)
        except (
            UnidentifiedImageError,
            ValueError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise MemberSessionFailure(
                status=409, code="CONFLICT", title="Uploaded file is not a valid profile photo"
            ) from exc
        approved_bucket = quote(self.approved_bucket, safe="")
        upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{approved_bucket}/o"
        approved = self._request(
            "POST",
            upload_url,
            headers={**headers, "Content-Type": "image/webp"},
            params={"uploadType": "media", "name": destination_key, "ifGenerationMatch": "0"},
            data=sanitized.getvalue(),
        )
        if approved.status_code == 412:
            # The database transaction may have failed after a prior successful
            # upload. Accept only an identical already-sanitised object so the
            # completion call can be safely retried.
            encoded_destination = quote(destination_key, safe="")
            approved_url = (
                f"https://storage.googleapis.com/storage/v1/b/{approved_bucket}/o/{encoded_destination}"
            )
            existing = self._request("GET", approved_url, headers=headers, params={"alt": "media"})
            if existing.status_code != 200 or not hmac.compare_digest(
                hashlib.sha256(existing.content).digest(),
                hashlib.sha256(sanitized.getvalue()).digest(),
            ):
                raise unavailable()
        elif approved.status_code == 200:
            try:
                approved_name = approved.json().get("name")
            except (ValueError, TypeError) as exc:
                raise unavailable() from exc
            if approved_name != destination_key:
                raise unavailable()
        else:
            raise unavailable()
        generation = metadata.get("generation")
        deleted = self._request(
            "DELETE", source_url, headers=headers, params={"ifGenerationMatch": generation}
        )
        # A seven-day bucket lifecycle is the second cleanup path. Once the
        # approved object exists, a temporary quarantine-delete failure must
        # not turn a successful profile update into a user-visible failure.
        _ = deleted.status_code


class PostgresProfilePhotoService:
    def __init__(
        self, authorization, profile_service, storage, *, expires_seconds=300, now=lambda: datetime.now(UTC)
    ):
        self.authorization = authorization
        self.profile_service = profile_service
        self.storage = storage
        self.expires_seconds = expires_seconds
        self.now = now

    async def start(self, token, request: PhotoUploadRequest, trace_id):
        owner = self.authorization._proof(token)[0]
        upload_id = uuid4()
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[request.content_type]
        object_key = f"profile-photo-quarantine/{owner}/{upload_id}.{extension}"
        now = self.now().astimezone(UTC)
        expires_at = now + timedelta(seconds=self.expires_seconds)
        async with self.authorization.transaction(token, Permission.OWN_PROFILE, target=owner) as (
            connection,
            _,
        ):
            exists = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM engagement_app.user_profiles WHERE user_id=$1)", owner
            )
            if exists is not True:
                raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Profile has not been created")
            await connection.execute(
                """INSERT INTO engagement_app.profile_photo_uploads
                   (id,user_id,quarantine_object_key,content_type,size_bytes,sha256,expires_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7)""",
                upload_id,
                owner,
                object_key,
                request.content_type,
                request.size_bytes,
                request.sha256,
                expires_at,
            )
        url, headers = await self.storage.upload_url(object_key, request, self.expires_seconds)
        return UploadAuthorisation(
            upload_id=upload_id,
            upload_url=url,
            required_headers=headers,
            expires_at=expires_at,
        )

    async def complete(self, token, upload_id: UUID, trace_id):
        owner = self.authorization._proof(token)[0]
        async with self.authorization.transaction(token, Permission.OWN_PROFILE, target=owner) as (
            connection,
            _,
        ):
            row = await connection.fetchrow(
                """SELECT upload.*, profile.photo_object_key AS previous_photo_object_key
                   FROM engagement_app.profile_photo_uploads AS upload
                   JOIN engagement_app.user_profiles AS profile ON profile.user_id=upload.user_id
                   WHERE upload.id=$1 AND upload.user_id=$2 FOR UPDATE OF upload, profile""",
                upload_id,
                owner,
            )
            if row is None:
                raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Photo upload was not found")
            if row["completed_at"] is not None:
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="Photo upload is already complete"
                )
            now = self.now().astimezone(UTC)
            if row["expires_at"] <= now:
                raise MemberSessionFailure(status=409, code="CONFLICT", title="Photo upload has expired")
            expected = PhotoUploadRequest(
                content_type=row["content_type"], size_bytes=row["size_bytes"], sha256=row["sha256"]
            )
            approved_key = f"profile-photos/{owner}/{upload_id}.webp"
            await self.storage.validate_and_promote(row["quarantine_object_key"], approved_key, expected)
            await connection.execute(
                """UPDATE engagement_app.profile_photo_uploads
                   SET approved_object_key=$2,completed_at=$3 WHERE id=$1""",
                upload_id,
                approved_key,
                now,
            )
            await connection.execute(
                "UPDATE engagement_app.user_profiles SET photo_object_key=$2,updated_at=$3 WHERE user_id=$1",
                owner,
                approved_key,
                now,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'profile.photo.updated','user_profile',$2,$3,'{}'::jsonb)""",
                owner,
                str(owner),
                trace_id,
            )
            result = await self.profile_service._read(connection, owner)
            previous_key = row.get("previous_photo_object_key")
        if previous_key and previous_key != approved_key:
            try:
                await self.storage.delete_approved(previous_key)
            except MemberSessionFailure:
                # The new photo is already committed. A failed best-effort
                # deletion must not hide the successful profile update.
                pass
        return result
