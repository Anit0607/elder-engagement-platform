from __future__ import annotations

import hmac
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import jwt
import pytest

from app.member_auth import AuthenticationDependencyUnavailable, MemberRecord
from app.postgres_session_issuer import PostgresSessionIssuer

MEMBER_ID = UUID("11111111-1111-4111-8111-111111111111")
INSTALLATION_ID = UUID("22222222-2222-4222-8222-222222222222")
SIGNING_KEY = b"synthetic-signing-material-32-bytes-minimum"
REFRESH_PEPPER = b"synthetic-refresh-material-32-bytes-minimum"
ISSUER = "https://api.synthetic.example"


class AsyncContext(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeConnection:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.calls = []

    async def execute(self, query, *values):
        if self.failures:
            raise self.failures.pop(0)
        self.calls.append((query, values))
        return "INSERT 0 1"


class FakePool:
    def __init__(self, connection):
        self.connection = connection
        self.acquisitions = 0

    def acquire(self):
        self.acquisitions += 1
        return AsyncContext(self.connection)


def member() -> MemberRecord:
    now = datetime.now(UTC)
    return MemberRecord(
        id=MEMBER_ID,
        role="member",
        status="active",
        display_name="Synthetic Member",
        preferred_language="bn",
        profile_complete=True,
        created_at=now,
        updated_at=now,
    )


def issuer(pool, **overrides) -> PostgresSessionIssuer:
    options = {
        "signing_key": SIGNING_KEY,
        "refresh_pepper": REFRESH_PEPPER,
        "issuer": ISSUER,
        "now": lambda: datetime.now(UTC),
    }
    options.update(overrides)
    return PostgresSessionIssuer(pool, **options)


@pytest.mark.anyio
async def test_session_contains_minimal_signed_claims_and_hashed_refresh_secret():
    connection = FakeConnection()
    result = await issuer(FakePool(connection)).issue(
        member(), INSTALLATION_ID, "android", "Synthetic Android"
    )
    claims = jwt.decode(
        result.access_token,
        SIGNING_KEY,
        algorithms=["HS256"],
        audience="amiko-api",
        issuer=ISSUER,
    )
    assert claims["sub"] == str(MEMBER_ID)
    assert claims["role"] == "member"
    assert {"sid", "jti", "iat", "nbf", "exp"} <= claims.keys()
    assert "phone_number" not in claims
    assert "display_name" not in claims
    assert result.expires_in_seconds == 600

    stored = connection.calls[0][1]
    assert stored[1] == MEMBER_ID
    assert stored[4] == INSTALLATION_ID
    assert stored[5:7] == ("android", "Synthetic Android")
    assert result.refresh_token not in stored
    expected_hash = hmac.digest(
        REFRESH_PEPPER, result.refresh_token.encode(), "sha256"
    ).hex()
    assert stored[3] == expected_hash


@pytest.mark.anyio
async def test_unique_collision_reissues_both_tokens_and_retries_once():
    connection = FakeConnection([asyncpg.UniqueViolationError("synthetic collision")])
    pool = FakePool(connection)
    result = await issuer(pool).issue(member(), INSTALLATION_ID, "ios", None)
    assert result.refresh_token.startswith("amr1_")
    assert pool.acquisitions == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [asyncpg.CannotConnectNowError("synthetic outage"), OSError("synthetic network outage")],
)
async def test_database_outage_is_reported_as_retryable_dependency_failure(failure):
    connection = FakeConnection([failure])
    with pytest.raises(AuthenticationDependencyUnavailable):
        await issuer(FakePool(connection)).issue(
            member(), INSTALLATION_ID, "android", None
        )


@pytest.mark.anyio
async def test_unique_collisions_stop_after_bounded_attempts():
    collisions = [asyncpg.UniqueViolationError("synthetic collision")] * 3
    with pytest.raises(AuthenticationDependencyUnavailable):
        await issuer(FakePool(FakeConnection(collisions))).issue(
            member(), INSTALLATION_ID, "android", None
        )


@pytest.mark.parametrize(
    "override",
    [
        {"signing_key": b"short"},
        {"refresh_pepper": b"short"},
        {"issuer": "http://not-secure.example"},
        {"issuer": "https://api.synthetic.example/unexpected-path"},
        {"refresh_pepper": SIGNING_KEY},
        {"audience": ""},
        {"access_token_minutes": 31},
        {"refresh_token_days": 91},
        {"retry_attempts": 0},
    ],
)
def test_unsafe_session_configuration_is_rejected(override):
    with pytest.raises(ValueError):
        issuer(FakePool(FakeConnection()), **override)


@pytest.mark.anyio
async def test_session_clock_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        await issuer(
            FakePool(FakeConnection()), now=lambda: datetime(2026, 9, 12)
        ).issue(member(), INSTALLATION_ID, "android", None)


@pytest.mark.anyio
async def test_non_member_or_inactive_account_cannot_receive_member_session():
    for record in [replace(member(), role="administrator"), replace(member(), status="suspended")]:
        with pytest.raises(ValueError, match="only an active Member"):
            await issuer(FakePool(FakeConnection())).issue(
                record, INSTALLATION_ID, "android", None
            )
