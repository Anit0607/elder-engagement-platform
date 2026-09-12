from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.session_controls import PostgresSessionControls, SessionSummary, UnconfiguredSessionControls

KEY = b"synthetic-signing-material-at-least-32-bytes"
USER, SESSION, FAMILY = uuid4(), uuid4(), uuid4()
NOW = datetime.now(UTC)


def proof(**changes):
    claims = dict(iss="https://api.synthetic.example", aud="amiko-api", sub=str(USER), sid=str(SESSION),
                  jti=str(uuid4()), role="member", iat=int(NOW.timestamp()), nbf=int(NOW.timestamp()),
                  exp=int((NOW + timedelta(minutes=10)).timestamp()))
    claims.update(changes)
    return jwt.encode(claims, KEY, algorithm="HS256")


class FakePool:
    def __init__(self):
        self.user = {"role": "member", "status": "active"}
        self.session = {"id": SESSION}
        self.target = {"token_family_id": FAMILY}
        self.calls = []
        self.error = None
        self.rows = [dict(id=SESSION, installation_id=uuid4(), platform="android", device_name=None,
                          created_at=NOW, last_seen_at=NOW)]

    @asynccontextmanager
    async def acquire(self):
        if self.error:
            raise self.error
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "app_users" in sql:
            return self.user
        if "token_family_id" in sql:
            return self.target
        return self.session

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


def manager(pool):
    return PostgresSessionControls(pool, signing_key=KEY,
                                  refresh_pepper=b"synthetic-refresh-material-at-least-32-bytes",
                                  issuer="https://api.synthetic.example", now=lambda: NOW)


@pytest.mark.anyio
async def test_list_returns_only_safe_summary_and_current_flag():
    pool = FakePool()
    rows = await manager(pool).list_sessions(proof())
    assert rows[0].current is True
    assert "token" not in str(rows[0].model_dump())
    assert "revoked_at IS NULL" in pool.calls[-1][0]
    assert "replaced_by_session_id IS NULL" in pool.calls[-1][0]
    assert pool.calls[-1][1] == (USER, NOW)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["logout", "revoke"])
async def test_removal_is_scoped_to_owner_and_entire_family(operation):
    pool = FakePool()
    controls = manager(pool)
    if operation == "logout":
        await controls.logout(proof())
    else:
        await controls.revoke(proof(), uuid4())
    assert pool.calls[-1][1] == (USER, FAMILY, NOW)
    assert "user_id=$1 AND token_family_id=$2" in pool.calls[-1][0]


@pytest.mark.anyio
@pytest.mark.parametrize("user,status", [
    (None, 401), ({"role": "administrator", "status": "active"}, 401),
    ({"role": "member", "status": "deleted"}, 401),
    ({"role": "member", "status": "pending"}, 401),
    ({"role": "member", "status": "suspended"}, 403),
])
async def test_account_state_is_authoritative(user, status):
    pool = FakePool()
    pool.user = user
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).list_sessions(proof())
    assert error.value.status == status
    assert len(pool.calls) == 1


@pytest.mark.anyio
async def test_revoked_or_expired_current_session_cannot_remove_devices():
    pool = FakePool()
    pool.session = None
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).logout(proof())
    assert error.value.status == 401
    assert len(pool.calls) == 2


@pytest.mark.anyio
async def test_foreign_or_missing_target_returns_same_not_found():
    pool = FakePool()
    pool.target = None
    with pytest.raises(MemberSessionFailure) as error:
        await manager(pool).revoke(proof(), uuid4())
    assert error.value.status == 404
    assert pool.calls[-1][1][1] == USER


@pytest.mark.anyio
@pytest.mark.parametrize("error", [OSError(), TimeoutError(), asyncpg.PostgresError()])
async def test_database_failure_is_safe_and_retryable(error):
    pool = FakePool()
    pool.error = error
    with pytest.raises(MemberSessionFailure) as result:
        await manager(pool).list_sessions(proof())
    assert result.value.status == 503
    assert result.value.retryable is True


@pytest.mark.parametrize("changes", [
    {"iss": "https://foreign.example"}, {"aud": "foreign"}, {"role": "administrator"},
    {"sub": "invalid"}, {"sid": None}, {"jti": "invalid"}, {"iat": True},
    {"exp": int((NOW - timedelta(minutes=1)).timestamp())},
    {"exp": int((NOW + timedelta(hours=2)).timestamp())}, {"nbf": int(NOW.timestamp()) - 1},
    {"aud": ["amiko-api"]},
])
def test_rejects_invalid_claims(changes):
    with pytest.raises(MemberSessionFailure):
        manager(FakePool())._claims(proof(**changes))


@pytest.mark.parametrize("token", ["", "invalid", "x" * 8193, None])
def test_rejects_invalid_token_shapes(token):
    with pytest.raises(MemberSessionFailure):
        manager(FakePool())._claims(token)


def test_rejects_wrong_key_missing_claim_and_algorithm():
    controls = manager(FakePool())
    for token in [jwt.encode({"sub": str(USER)}, KEY, algorithm="HS256"),
                  jwt.encode({"sub": str(USER)}, KEY, algorithm="HS384"),
                  proof()[:-5] + "xxxxx"]:
        with pytest.raises(MemberSessionFailure):
            controls._claims(token)


class FakeControls:
    async def list_sessions(self, token):
        assert token == "synthetic-access-token"  # noqa: S105 - deliberately nonfunctional fixture
        return [SessionSummary(id=SESSION, installation_id=uuid4(), platform="ios", current=True,
                               created_at=NOW, last_seen_at=NOW)]

    async def logout(self, token):
        assert token == "synthetic-access-token"  # noqa: S105 - deliberately nonfunctional fixture

    async def revoke(self, token, target):
        assert token == "synthetic-access-token"  # noqa: S105 - deliberately nonfunctional fixture
        assert isinstance(target, type(SESSION))


def test_routes_return_contract_shapes_and_bodyless_logout(settings):
    with TestClient(create_app(settings, session_controls_handler=FakeControls())) as client:
        headers = {"Authorization": "Bearer synthetic-access-token"}
        result = client.get("/v1/me/sessions", headers=headers)
        assert result.status_code == 200
        assert result.json()[0]["current"] is True
        assert "installationId" in result.json()[0]
        for result in [client.post("/v1/auth/logout", headers=headers),
                       client.delete(f"/v1/me/sessions/{SESSION}", headers=headers)]:
            assert result.status_code == 204
            assert result.content == b""
            assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("header", ["", "Basic synthetic", "Bearer ", "Bearer x y", "Bearer x\ty"])
def test_routes_reject_missing_or_malformed_authentication(settings, header):
    with TestClient(create_app(settings, session_controls_handler=FakeControls())) as client:
        assert client.get("/v1/me/sessions", headers={"Authorization": header}).status_code == 401


def test_unconfigured_controls_fail_closed(settings):
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer synthetic-access-token"}
        assert client.get("/v1/me/sessions", headers=headers).status_code == 503


@pytest.mark.anyio
async def test_unconfigured_logout_and_removal():
    controls = UnconfiguredSessionControls()
    for operation in [controls.logout("synthetic"), controls.revoke("synthetic", SESSION)]:
        with pytest.raises(MemberSessionFailure) as error:
            await operation
        assert error.value.status == 503
