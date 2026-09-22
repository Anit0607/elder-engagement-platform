"""Read-only readiness checks for the connected development runtime.

No check creates user data, uploads an object, or returns dependency details to
the caller. External probes are cached briefly to avoid turning the public
readiness route into an unbounded Google API request generator.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

import google.auth.exceptions
import google.auth.transport.requests
import requests

from app.readiness import DependencyStatus

FIREBASE_CERTIFICATES_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)


class DatabaseProbe:
    def __init__(self, pool):
        self._pool = pool

    async def check(self) -> DependencyStatus:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval("SELECT 1")
        return DependencyStatus(ready=value == 1)


class RateLimitStoreProbe:
    """The live sign-in limits are held in PostgreSQL, not the legacy memory setting."""

    def __init__(self, pool, *, staff_enabled: bool):
        self._pool = pool
        self._staff_enabled = staff_enabled

    async def check(self) -> DependencyStatus:
        async with self._pool.acquire() as connection:
            member_count = await connection.fetchval(
                "SELECT count(*) FROM engagement_app.auth_sessions WHERE FALSE"
            )
            staff_count = 0
            if self._staff_enabled:
                staff_count = await connection.fetchval(
                    "SELECT count(*) FROM engagement_app.staff_credentials WHERE FALSE"
                )
        return DependencyStatus(ready=member_count == 0 and staff_count == 0)


class BoundedCredentialRequest(google.auth.transport.requests.Request):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 2
        return super().__call__(*args, **kwargs)


class CachedExternalProbe:
    def __init__(self, *, cache_seconds: int = 30, now=time.monotonic):
        self._cache_seconds = cache_seconds
        self._now = now
        self._expires_at = 0.0
        self._result: DependencyStatus | None = None
        self._lock = asyncio.Lock()

    async def check(self) -> DependencyStatus:
        if self._result is not None and self._now() < self._expires_at:
            return self._result
        async with self._lock:
            if self._result is not None and self._now() < self._expires_at:
                return self._result
            try:
                ready = await asyncio.to_thread(self._check_sync)
            except (
                OSError,
                ValueError,
                TypeError,
                requests.RequestException,
                google.auth.exceptions.GoogleAuthError,
            ):
                ready = False
            self._result = DependencyStatus(ready=ready is True)
            self._expires_at = self._now() + self._cache_seconds
            return self._result

    def _check_sync(self) -> bool:
        raise NotImplementedError


class IdentityVerifierProbe(CachedExternalProbe):
    def __init__(self, *, requester=requests.get, **kwargs):
        super().__init__(**kwargs)
        self._requester = requester

    def _check_sync(self) -> bool:
        response = self._requester(
            FIREBASE_CERTIFICATES_URL,
            timeout=2,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return False
        certificates = response.json()
        return bool(
            isinstance(certificates, dict)
            and certificates
            and all(
                isinstance(certificate, str) and "-----BEGIN CERTIFICATE-----" in certificate
                for certificate in certificates.values()
            )
        )


class ObjectStorageProbe(CachedExternalProbe):
    def __init__(self, storage, *, requester=requests.get, **kwargs):
        super().__init__(**kwargs)
        self._credentials = storage.credentials
        self._requester = requester
        self._targets = (
            (storage.uploads_bucket, "profile-photo-quarantine/__readiness_missing__"),
            (storage.uploads_bucket, "content-quarantine/__readiness_missing__"),
            (storage.approved_bucket, "profile-photos/__readiness_missing__"),
            (storage.approved_bucket, "content/__readiness_missing__"),
        )

    def _check_sync(self) -> bool:
        if not self._credentials.valid:
            self._credentials.refresh(BoundedCredentialRequest())
        token = self._credentials.token
        if not token:
            return False
        for bucket, object_name in self._targets:
            address = (
                "https://storage.googleapis.com/storage/v1/b/"
                f"{quote(bucket, safe='')}/o/{quote(object_name, safe='')}"
            )
            response = self._requester(
                address,
                headers={"Authorization": f"Bearer {token}"},
                timeout=2,
                allow_redirects=False,
            )
            if response.status_code not in {200, 404}:
                return False
        return True
