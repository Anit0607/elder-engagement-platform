from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.session_controls import UnconfiguredSessionControls
from app.session_refresh import PostgresSessionRefresh

KEY = b"synthetic-signing-material-at-least-32-bytes"
PEPPER = b"synthetic-refresh-material-at-least-32-bytes"
TOKEN = "amr1_" + "a" * 64  # noqa: S105 - nonfunctional test fixture
NOW = datetime.now(UTC)
USER, SESSION, FAMILY, INSTALLATION = uuid4(), uuid4(), uuid4(), uuid4()


class FakePool:
    def __init__(self):
        self.owner = {"user_id": USER}
        self.user = dict(id=USER, role="member", status="active", created_at=NOW, updated_at=NOW,
                         display_name="Synthetic member", preferred_language="bn", profile_complete=True)
        self.session = dict(id=SESSION, token_family_id=FAMILY, installation_id=INSTALLATION,
                            platform="android", device_name=None, expires_at=NOW + timedelta(days=30),
                            revoked_at=None, replaced_by_session_id=None)
        self.calls = []
        self.transaction_exits = []
        self.error = None
        self.collisions = 0
        self.write_error = None
        self.commit_error = None

    @asynccontextmanager
    async def acquire(self):
        if self.error:
            raise self.error
        yield self

    @asynccontextmanager
    async def transaction(self):
        try:
            yield
        except BaseException as error:
            self.transaction_exits.append(type(error))
            raise
        else:
            if self.commit_error:
                raise self.commit_error
            self.transaction_exits.append(None)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT user_id" in sql:
            return self.owner
        if "app_users" in sql:
            return self.user
        return self.session

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if "UPDATE" in sql and self.write_error:
            raise self.write_error
        if "INSERT" in sql and self.collisions:
            self.collisions -= 1
            raise asyncpg.UniqueViolationError("synthetic collision")


def manager(pool, **changes):
    return PostgresSessionRefresh(pool, signing_key=KEY, refresh_pepper=PEPPER,
                                  issuer="https://api.synthetic.example", now=lambda: NOW, **changes)


@pytest.mark.anyio
async def test_rotation_preserves_identity_family_installation_and_absolute_expiry():
    pool = FakePool()
    result = await manager(pool).refresh(TOKEN)
    claims = jwt.decode(result.access_token, KEY, algorithms=["HS256"], audience="amiko-api")
    assert result.user.id == USER
    assert result.user.display_name == "Synthetic member"
    assert result.expires_in_seconds == 600
    assert claims["sub"] == str(USER)
    assert result.refresh_token != TOKEN
    assert len(result.refresh_token) == 69
    insert = pool.calls[-2][1]
    assert UUID(claims["sid"]) == insert[0]
    assert insert[1:3] == (USER, FAMILY)
    assert insert[3] == hmac.digest(PEPPER, result.refresh_token.encode(), "sha256").hex()
    assert insert[4:] == (INSTALLATION, "android", None, NOW, pool.session["expires_at"])
    assert pool.calls[-1][1] == (SESSION, insert[0], NOW)
    assert pool.calls[0][1] == (hmac.digest(PEPPER, TOKEN.encode(), "sha256").hex(),)
    assert "FOR UPDATE OF u" in pool.calls[1][0]
    assert "FOR UPDATE" in pool.calls[2][0]
    assert all(TOKEN not in str(call) and result.refresh_token not in str(call) for call in pool.calls)
    assert pool.transaction_exits == [None]


@pytest.mark.anyio
async def test_reuse_revokes_owned_family_and_commits_before_returning_conflict():
    pool = FakePool()
    pool.session["replaced_by_session_id"] = uuid4()
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(TOKEN)
    assert (error.value.status, error.value.code) == (409, "REFRESH_TOKEN_REUSED")
    assert pool.calls[-1][1] == (USER, FAMILY, NOW)
    assert "user_id=$1 AND token_family_id=$2" in pool.calls[-1][0]
    assert pool.transaction_exits == [None]
    assert not any("INSERT" in sql for sql, _ in pool.calls)


@pytest.mark.anyio
@pytest.mark.parametrize("token", [None, "", "amr1_" + "a" * 63, "amr1_" + "a" * 65,
                                   "amr1_" + "+" * 64, "amr2_" + "a" * 64])
async def test_invalid_token_shape_never_queries_database(token):
    pool = FakePool()
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(token)
    assert error.value.code == "INVALID_REFRESH_TOKEN"
    assert not pool.calls


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["owner", "user", "session"])
async def test_missing_records_fail_closed(missing):
    pool = FakePool()
    setattr(pool, missing, None)
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(TOKEN)
    assert error.value.status == 401
    assert pool.transaction_exits == [MemberSessionFailure]


@pytest.mark.anyio
@pytest.mark.parametrize("field,value,status,code", [
    ("role", "administrator", 401, "INVALID_REFRESH_TOKEN"),
    ("role", "contributor", 401, "INVALID_REFRESH_TOKEN"),
    ("status", "deleted", 401, "INVALID_REFRESH_TOKEN"),
    ("status", "pending", 401, "INVALID_REFRESH_TOKEN"),
    ("status", "suspended", 403, "ACCOUNT_SUSPENDED"),
])
async def test_current_account_state_controls_refresh(field, value, status, code):
    pool = FakePool()
    pool.user[field] = value
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(TOKEN)
    assert (error.value.status, error.value.code) == (status, code)
    assert len(pool.calls) == 2


@pytest.mark.anyio
async def test_revoked_family_cannot_refresh_even_with_replaced_token():
    pool = FakePool()
    pool.session.update(revoked_at=NOW, replaced_by_session_id=uuid4())
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(TOKEN)
    assert (error.value.status, error.value.code) == (401, "SESSION_REVOKED")
    assert len(pool.calls) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("seconds", [-100, 0, 59, 60, 100, 600])
async def test_access_lifetime_is_capped_by_remaining_original_expiry(seconds):
    pool = FakePool()
    pool.session["expires_at"] = NOW + timedelta(seconds=seconds)
    if seconds < 60:
        with pytest.raises(MemberSessionFailure) as error:
            await manager(pool).refresh(TOKEN)
        assert error.value.status == 401
        assert not any("INSERT" in sql for sql, _ in pool.calls)
    else:
        result = await manager(pool).refresh(TOKEN)
        assert result.expires_in_seconds == seconds
        assert pool.calls[-2][1][-1] == NOW + timedelta(seconds=seconds)


@pytest.mark.anyio
@pytest.mark.parametrize("error", [OSError("private"), TimeoutError("private"),
                                   asyncpg.PostgresError("private")])
async def test_database_outage_returns_safe_dependency_error(error):
    pool = FakePool()
    pool.error = error
    with pytest.raises(MemberSessionFailure) as result:
        await manager(pool).refresh(TOKEN)
    assert result.value.status == 503
    # Never encourage replay after a database/commit outcome is uncertain.
    assert result.value.retryable is False
    assert "private" not in result.value.title


@pytest.mark.anyio
@pytest.mark.parametrize("collisions", [1, 3])
async def test_token_collision_retries_are_bounded_and_transactional(collisions):
    pool = FakePool()
    pool.collisions = collisions
    if collisions == 1:
        result = await manager(pool).refresh(TOKEN)
        assert result.user.id == USER
        assert pool.transaction_exits == [asyncpg.UniqueViolationError, None]
    else:
        with pytest.raises(MemberSessionFailure) as error:
            await manager(pool).refresh(TOKEN)
        assert error.value.status == 503
        assert pool.transaction_exits == [asyncpg.UniqueViolationError] * 3


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["write_error", "commit_error"])
async def test_failure_after_insert_never_returns_credentials_or_advertises_replay(stage):
    pool = FakePool()
    setattr(pool, stage, OSError("synthetic private detail"))
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).refresh(TOKEN)
    assert error.value.status == 503
    assert error.value.retryable is False
    assert "private" not in error.value.title
    if stage == "write_error":
        assert pool.transaction_exits == [OSError]


@pytest.mark.anyio
async def test_naive_clock_is_rejected():
    controls = manager(FakePool())
    controls._now = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        await controls.refresh(TOKEN)


class FakeControls:
    def __init__(self, *, failure=None):
        self.failure = failure

    async def refresh(self, token):
        assert token == TOKEN
        if self.failure:
            raise self.failure
        return await manager(FakePool()).refresh(token)


def test_refresh_route_requires_body_credential_not_expired_access_header(settings, caplog):
    with TestClient(create_app(settings, session_controls_handler=FakeControls())) as client:
        result = client.post("/v1/auth/refresh", json={"refreshToken": TOKEN})
        assert result.status_code == 200
        assert result.json()["user"]["id"] == str(USER)
        assert result.json()["tokenType"] == "Bearer"
        assert result.headers["Cache-Control"] == "no-store"
        assert result.headers["X-Content-Type-Options"] == "nosniff"
        assert TOKEN not in caplog.text
        assert result.json()["refreshToken"] not in caplog.text


@pytest.mark.parametrize("status,code", [(401, "INVALID_REFRESH_TOKEN"), (403, "ACCOUNT_SUSPENDED"),
                                         (409, "REFRESH_TOKEN_REUSED"), (503, "DEPENDENCY_UNAVAILABLE")])
def test_refresh_route_safe_problem_shape(settings, status, code):
    failure = MemberSessionFailure(status=status, code=code, title="Sign in again")
    with TestClient(create_app(settings, session_controls_handler=FakeControls(failure=failure))) as client:
        result = client.post("/v1/auth/refresh", json={"refreshToken": TOKEN})
        assert result.status_code == status
        assert result.json()["code"] == code
        assert result.json()["traceId"]
        assert TOKEN not in result.text


@pytest.mark.parametrize("body", [{}, {"refreshToken": "short"}, {"refreshToken": 123},
                                  {"refreshToken": TOKEN, "role": "administrator"}])
def test_refresh_route_invalid_body_is_safe(settings, body):
    with TestClient(create_app(settings, session_controls_handler=FakeControls())) as client:
        result = client.post("/v1/auth/refresh", json=body)
        assert result.status_code == 400
        assert result.json()["code"] == "VALIDATION_FAILED"
        assert TOKEN not in result.text


@pytest.mark.anyio
async def test_unconfigured_refresh_fails_closed():
    with pytest.raises(MemberSessionFailure) as error:
        await UnconfiguredSessionControls().refresh(TOKEN)
    assert error.value.status == 503
    assert error.value.retryable is False


def test_unconfigured_refresh_route_fails_closed(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/auth/refresh", json={"refreshToken": TOKEN}).status_code == 503
