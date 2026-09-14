from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import jwt
import pytest

from app.member_auth import MemberSessionFailure
from app.staff_session_controls import PostgresStaffSessionControls

KEY = b"synthetic-staff-controls-signing-material-32-bytes"
NOW = datetime.now(UTC)
USER, SESSION, VERSION, FAMILY = (uuid4() for _ in range(4))
REFRESH = "amr1_" + "A" * 64


class Pool:
    def __init__(self):
        self.user = dict(id=USER, role="contributor", status="active", created_at=NOW, updated_at=NOW)
        self.credential = dict(
            credential_version=VERSION, second_factor_enabled=False, mfa_secret_ciphertext=None
        )
        self.session = dict(
            id=SESSION,
            token_family_id=FAMILY,
            installation_id=uuid4(),
            platform="web",
            device_name=None,
            expires_at=NOW + timedelta(days=30),
            revoked_at=None,
            replaced_by_session_id=None,
            staff_credential_version=VERSION,
        )
        self.owner = {"user_id": USER}
        self.profile = None
        self.selected = {"token_family_id": FAMILY}
        self.calls = []
        self.committed = False
        self.error = None
        self.insert_error = None

    @asynccontextmanager
    async def acquire(self):
        if self.error:
            raise self.error
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield self
        self.committed = True

    async def fetchrow(self, sql, *args):
        if "app_users" in sql:
            return self.user
        if "staff_credentials" in sql:
            return self.credential
        if "user_profiles" in sql:
            return self.profile
        if "SELECT user_id" in sql:
            return self.owner
        if "WHERE id=$1" in sql and args[0] != SESSION:
            return self.selected
        return self.session

    async def fetch(self, sql, *args):
        return [
            dict(
                id=SESSION,
                installation_id=uuid4(),
                platform="web",
                device_name=None,
                created_at=NOW,
                last_seen_at=NOW,
            )
        ]

    async def execute(self, sql, *args):
        if self.insert_error and "INSERT" in sql:
            raise self.insert_error
        self.calls.append((sql, args))


def controls(pool, clock=lambda: NOW):
    return PostgresStaffSessionControls(
        pool,
        signing_key=KEY,
        refresh_pepper=b"synthetic-staff-controls-refresh-material-32-bytes",
        issuer="https://api.synthetic.example",
        now=clock,
    )


def proof(**changes):
    values = dict(
        iss="https://api.synthetic.example",
        aud="amiko-api",
        sub=str(USER),
        sid=str(SESSION),
        jti=str(uuid4()),
        role="contributor",
        cv=str(VERSION),
        iat=int(NOW.timestamp()),
        nbf=int(NOW.timestamp()),
        exp=int((NOW + timedelta(minutes=10)).timestamp()),
    )
    values.update(changes)
    return jwt.encode(values, KEY, algorithm="HS256")


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "member"},
        {"cv": None},
        {"cv": "wrong"},
        {"sub": str(USER).upper()},
        {"iat": True},
        {"nbf": int(NOW.timestamp()) - 1},
        {"exp": int((NOW + timedelta(minutes=11)).timestamp())},
        {"aud": "wrong"},
        {"role": "unknown"},
    ],
)
def test_invalid_signed_claims_are_rejected(changes):
    with pytest.raises(MemberSessionFailure):
        controls(Pool())._claims(proof(**changes))


@pytest.mark.parametrize("value", [None, "short", "x" * 8193, "x" * 30])
def test_malformed_token_rejected(value):
    with pytest.raises(MemberSessionFailure):
        controls(Pool())._claims(value)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["list", "logout", "revoke"])
async def test_active_owner_operations_are_scoped(operation):
    pool = Pool()
    manager = controls(pool)
    if operation == "list":
        assert (await manager.list_sessions(proof()))[0].current
    elif operation == "logout":
        await manager.logout(proof())
        assert pool.calls[-1][1] == (USER, FAMILY, NOW)
    else:
        await manager.revoke(proof(), uuid4())
        assert pool.calls[-1][1] == (USER, FAMILY, NOW)
    assert pool.committed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "state,status",
    [
        ("missing", 401),
        ("member", 401),
        ("suspended", 403),
        ("invited", 401),
        ("credential-missing", 401),
        ("admin-disabled", 401),
        ("role-mismatch", 401),
        ("version-mismatch", 401),
        ("session-missing", 401),
        ("target-missing", 404),
    ],
)
async def test_authoritative_state_rejects_operations(state, status):
    pool = Pool()
    if state == "missing":
        pool.user = None
    elif state == "member":
        pool.user["role"] = "member"
    elif state in {"suspended", "invited"}:
        pool.user["status"] = state
    elif state == "credential-missing":
        pool.credential = None
    elif state == "admin-disabled":
        pool.user["role"] = "administrator"
    elif state == "role-mismatch":
        pool.user["role"] = "administrator"
        pool.credential.update(second_factor_enabled=True, mfa_secret_ciphertext=b"x" * 60)
    elif state == "version-mismatch":
        pool.credential["credential_version"] = uuid4()
    elif state == "session-missing":
        pool.session = None
    elif state == "target-missing":
        pool.selected = None
    with pytest.raises(MemberSessionFailure) as error:
        await controls(pool).revoke(proof(), uuid4())
    assert error.value.status == status


@pytest.mark.anyio
async def test_refresh_rotates_same_family_without_extending_expiry():
    pool = Pool()
    result = await controls(pool).refresh(REFRESH)
    assert result.user.role == "contributor"
    assert result.refresh_token != REFRESH
    insert = next(call for call in pool.calls if "INSERT" in call[0])
    assert insert[1][-2:] == (pool.session["expires_at"], VERSION)
    assert result.refresh_token not in insert[1]
    assert pool.committed


@pytest.mark.anyio
async def test_replay_revocation_commits_before_error():
    pool = Pool()
    pool.session["replaced_by_session_id"] = uuid4()
    with pytest.raises(MemberSessionFailure) as error:
        await controls(pool).refresh(REFRESH)
    assert error.value.code == "REFRESH_TOKEN_REUSED"
    assert pool.committed and pool.calls[-1][1] == (USER, FAMILY, NOW)


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["owner-missing", "session-missing", "wrong-version", "revoked", "expired"])
async def test_invalid_refresh_database_state(state):
    pool = Pool()
    if state == "owner-missing":
        pool.owner = None
    elif state == "session-missing":
        pool.session = None
    elif state == "wrong-version":
        pool.session["staff_credential_version"] = uuid4()
    elif state == "revoked":
        pool.session["revoked_at"] = NOW
    else:
        pool.session["expires_at"] = NOW + timedelta(seconds=30)
    with pytest.raises(MemberSessionFailure) as error:
        await controls(pool).refresh(REFRESH)
    assert error.value.status == 401


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "wrong", "amr1_" + "A" * 63])
async def test_malformed_refresh(value):
    with pytest.raises(MemberSessionFailure):
        await controls(Pool()).refresh(value)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["refresh", "logout"])
async def test_outage_is_not_automatically_retried(operation):
    pool = Pool()
    pool.error = TimeoutError()
    with pytest.raises(MemberSessionFailure) as error:
        if operation == "refresh":
            await controls(pool).refresh(REFRESH)
        else:
            await controls(pool).logout(proof())
    assert (error.value.status, error.value.retryable) == (503, False)


@pytest.mark.anyio
async def test_insert_collision_rolls_back_without_retry():
    pool = Pool()
    pool.insert_error = asyncpg.UniqueViolationError("synthetic collision")
    with pytest.raises(MemberSessionFailure) as error:
        await controls(pool).refresh(REFRESH)
    assert (error.value.status, error.value.retryable) == (503, False)
    assert not pool.committed


@pytest.mark.anyio
async def test_profile_is_returned_but_corrupt_profile_fails_closed():
    pool = Pool()
    pool.profile = dict(display_name="Synthetic staff", preferred_language="hi", profile_complete=True)
    assert (await controls(pool).refresh(REFRESH)).user.display_name == "Synthetic staff"
    pool.profile["display_name"] = ""
    with pytest.raises(MemberSessionFailure) as error:
        await controls(pool).refresh(REFRESH)
    assert error.value.status == 503


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        controls(Pool(), clock=lambda: NOW.replace(tzinfo=None))._clock()
