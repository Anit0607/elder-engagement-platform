from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.runtime_readiness import (
    DatabaseProbe,
    IdentityVerifierProbe,
    ObjectStorageProbe,
    RateLimitStoreProbe,
)


class FakeConnection:
    def __init__(self, values):
        self.values = values
        self.queries = []

    async def fetchval(self, query):
        self.queries.append(query)
        return self.values.pop(0)


class FakePool:
    def __init__(self, values):
        self.connection = FakeConnection(values)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class FakeResponse:
    def __init__(self, status_code=200, value=None):
        self.status_code = status_code
        self.value = value

    def json(self):
        return self.value


class FakeCredentials:
    valid = True
    token = "synthetic-token-not-a-real-secret"  # noqa: S105 - test-only fake


class FakeStorage:
    credentials = FakeCredentials()
    uploads_bucket = "synthetic-uploads"
    approved_bucket = "synthetic-approved"


@pytest.mark.anyio
async def test_database_probe_requires_real_successful_query():
    assert (await DatabaseProbe(FakePool([1])).check()).ready is True
    assert (await DatabaseProbe(FakePool([None])).check()).ready is False


@pytest.mark.anyio
async def test_rate_limit_probe_checks_member_and_staff_tables():
    pool = FakePool([0, 0])
    assert (await RateLimitStoreProbe(pool, staff_enabled=True).check()).ready is True
    assert "auth_sessions" in pool.connection.queries[0]
    assert "staff_credentials" in pool.connection.queries[1]
    assert (await RateLimitStoreProbe(FakePool([0, None]), staff_enabled=True).check()).ready is False
    assert (await RateLimitStoreProbe(FakePool([0]), staff_enabled=False).check()).ready is True


@pytest.mark.anyio
async def test_identity_probe_checks_certificates_and_caches_result():
    calls = []

    def requester(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(value={"key": "-----BEGIN CERTIFICATE-----\nfictional"})

    probe = IdentityVerifierProbe(requester=requester, now=lambda: 100)
    assert (await probe.check()).ready is True
    assert (await probe.check()).ready is True
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False
    rejected = IdentityVerifierProbe(requester=lambda *_args, **_kwargs: FakeResponse(503))
    empty = IdentityVerifierProbe(requester=lambda *_args, **_kwargs: FakeResponse(value={}))
    assert (await rejected.check()).ready is False
    assert (await empty.check()).ready is False


@pytest.mark.anyio
async def test_storage_probe_uses_read_only_checks_for_all_approved_prefixes():
    calls = []

    def requester(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(404)

    probe = ObjectStorageProbe(FakeStorage(), requester=requester, now=lambda: 100)
    assert (await probe.check()).ready is True
    assert (await probe.check()).ready is True
    assert len(calls) == 4
    assert all(call[1]["allow_redirects"] is False for call in calls)
    assert all("/o/" in call[0] for call in calls)
    assert all("Authorization" in call[1]["headers"] for call in calls)
    for prefix in ("profile-photo-quarantine", "content-quarantine", "profile-photos", "content"):
        assert any(prefix in call[0] for call in calls)


@pytest.mark.anyio
async def test_storage_probe_fails_closed_when_access_is_denied():
    probe = ObjectStorageProbe(
        FakeStorage(), requester=lambda *_args, **_kwargs: FakeResponse(403)
    )
    assert (await probe.check()).ready is False
