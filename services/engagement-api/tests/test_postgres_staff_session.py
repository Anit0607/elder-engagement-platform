from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import jwt
import pyotp
import pytest

from app.member_auth import MemberSessionFailure
from app.postgres_staff_session import PostgresStaffSessionService
from app.staff_auth import StaffSessionRequest
from app.staff_credentials import StaffAuthenticator, StaffCredentialVerifier, StaffPasswords

NOW = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)
PASSWORD = "non-working-staff-unit-fixture"  # noqa: S105 -- never a runtime credential
KEY = b"unit-only-staff-signing-material-32-bytes"
PEPPER = b"unit-only-staff-refresh-material-32-bytes"
SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


class Context(AbstractAsyncContextManager):
    def __init__(self, value, connection=None):
        self.value, self.connection = value, connection

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, typ, value, traceback):
        if self.connection:
            self.connection.committed = typ is None
            if self.connection.commit_error and typ is None:
                raise self.connection.commit_error
        return False


class Connection:
    def __init__(self, rows, recent=0):
        self.fetchrow = AsyncMock(side_effect=rows)
        self.fetchval = AsyncMock(return_value=recent)
        self.execute = AsyncMock()
        self.committed = False
        self.commit_error = None

    def transaction(self):
        return Context(self, self)


class Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return Context(self.connection)


@pytest.fixture(scope="module")
def passwords():
    return StaffPasswords()


def setup(
    passwords,
    *,
    role="contributor",
    status="active",
    enabled=False,
    attempts=0,
    locked=None,
    counter=None,
    profile=None,
    recent=0,
    missing=False,
    clock=lambda: NOW,
):
    owner = {"id": uuid4(), "role": role, "status": status, "created_at": NOW, "updated_at": NOW}
    authenticator = StaffAuthenticator(bytes(range(32)))
    stored = {
        "password_hash": passwords.hash(PASSWORD),
        "second_factor_enabled": enabled,
        "mfa_secret_ciphertext": authenticator.protect(owner["id"], SEED) if enabled else None,
        "last_accepted_totp_step": counter,
        "locked_until": locked,
        "failed_attempts": attempts,
        "credential_version": uuid4(),
    }
    rows = [owner]
    if role in {"contributor", "administrator"}:
        rows.append(None if missing else stored)
    rows.append(profile)
    connection = Connection(rows, recent)
    service = PostgresStaffSessionService(
        Pool(connection),
        verifier=StaffCredentialVerifier(passwords, authenticator),
        signing_key=KEY,
        refresh_pepper=PEPPER,
        issuer="https://api.synthetic.example",
        now=clock,
    )
    return owner, stored, connection, service


def request(**kwargs):
    values = {
        "username": "synthetic-staff",
        "password": PASSWORD,
        "installationId": uuid4(),
        "platform": "web",
    }
    values.update(kwargs)
    return StaffSessionRequest(**values)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "role,enabled", [("contributor", False), ("contributor", True), ("administrator", True)]
)
async def test_success_persists_version_and_code_with_session(passwords, role, enabled):
    owner, stored, connection, service = setup(
        passwords,
        role=role,
        enabled=enabled,
        attempts=3,
        profile={"display_name": "Synthetic staff", "preferred_language": "bn", "profile_complete": True},
    )
    result = await service.create(request(secondFactorCode=pyotp.TOTP(SEED).at(NOW)))
    claims = jwt.decode(
        result.access_token,
        KEY,
        algorithms=["HS256"],
        audience="amiko-api",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert claims["role"] == role
    assert claims["cv"] == str(stored["credential_version"])
    assert claims["sub"] == str(owner["id"])
    assert result.user.display_name == "Synthetic staff"
    assert connection.committed
    update, insert = connection.execute.call_args_list
    assert update.args[1:] == (owner["id"], int(NOW.timestamp()) // 30 if enabled else None)
    assert insert.args[-1] == stored["credential_version"]
    assert result.refresh_token not in insert.args


@pytest.mark.anyio
async def test_no_profile_and_password_only_contributor(passwords):
    _, _, connection, service = setup(passwords)
    result = await service.create(request())
    assert result.user.profile_complete is False
    assert result.user.display_name is None
    assert connection.committed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "attempts,locked,expected", [(0, None, 1), (4, None, 5), (5, NOW - timedelta(seconds=1), 1)]
)
async def test_wrong_password_is_committed_before_error(passwords, attempts, locked, expected):
    owner, _, connection, service = setup(passwords, attempts=attempts, locked=locked)
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request(password=PASSWORD + "-wrong"))
    assert error.value.status == 401
    assert connection.committed
    assert connection.execute.call_count == 1
    assert connection.execute.call_args.args[1:] == (
        owner["id"],
        expected,
        NOW + timedelta(minutes=10) if expected == 5 else None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kwargs,code,status",
    [
        ({"role": "member"}, "AUTHENTICATION_FAILED", 401),
        ({"missing": True}, "AUTHENTICATION_FAILED", 401),
        ({"status": "suspended"}, "ACCOUNT_SUSPENDED", 403),
        ({"status": "invited"}, "AUTHENTICATION_FAILED", 401),
        ({"locked": NOW + timedelta(minutes=1)}, "RATE_LIMITED", 429),
        ({"role": "administrator"}, "DEPENDENCY_UNAVAILABLE", 503),
        ({"role": "administrator", "enabled": True}, "MFA_REQUIRED", 403),
        ({"recent": 5}, "RATE_LIMITED", 429),
    ],
)
async def test_no_token_or_writes_for_rejected_state(passwords, kwargs, code, status):
    _, _, connection, service = setup(passwords, **kwargs)
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request())
    assert (error.value.code, error.value.status) == (code, status)
    assert connection.committed
    connection.execute.assert_not_called()


@pytest.mark.anyio
async def test_unknown_user_runs_dummy_check_without_write(passwords):
    _, _, connection, service = setup(passwords)
    connection.fetchrow.side_effect = [None]
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request())
    assert error.value.status == 401
    connection.execute.assert_not_called()
    assert connection.committed


@pytest.mark.anyio
@pytest.mark.parametrize("counter", [None, int(NOW.timestamp()) // 30])
async def test_wrong_or_reused_code_commits_failed_attempt(passwords, counter):
    _, _, connection, service = setup(passwords, role="administrator", enabled=True, counter=counter)
    code = pyotp.TOTP(SEED).at(NOW) if counter else "not-used"
    if code == "not-used":
        # Choose a code outside all accepted windows rather than assume 000000.
        valid = {pyotp.TOTP(SEED).at(NOW + timedelta(seconds=delta)) for delta in (-30, 0, 30)}
        code = next(f"{i:06d}" for i in range(10) if f"{i:06d}" not in valid)
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request(secondFactorCode=code))
    assert error.value.status == 401
    assert connection.committed
    assert connection.execute.call_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [
        asyncpg.CannotConnectNowError("synthetic outage"),
        OSError("synthetic outage"),
        TimeoutError("synthetic timeout"),
    ],
)
async def test_database_outage_is_not_automatically_retried(passwords, failure):
    _, _, connection, service = setup(passwords)
    connection.fetchrow.side_effect = failure
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request())
    assert (error.value.status, error.value.retryable) == (503, False)
    assert not connection.committed


@pytest.mark.anyio
async def test_session_insert_failure_rolls_back_code_update(passwords):
    _, _, connection, service = setup(passwords, role="administrator", enabled=True)
    connection.execute.side_effect = [None, asyncpg.UniqueViolationError("synthetic collision")]
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request(secondFactorCode=pyotp.TOTP(SEED).at(NOW)))
    assert (error.value.status, error.value.retryable) == (503, False)
    assert not connection.committed


@pytest.mark.anyio
async def test_lost_commit_acknowledgement_returns_no_tokens(passwords):
    _, _, connection, service = setup(passwords)
    connection.commit_error = OSError("synthetic lost commit acknowledgement")
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request())
    assert (error.value.status, error.value.retryable) == (503, False)


@pytest.mark.anyio
async def test_invalid_stored_profile_rolls_back_before_code_or_session(passwords):
    _, _, connection, service = setup(
        passwords, profile={"display_name": "", "preferred_language": "bn", "profile_complete": False}
    )
    with pytest.raises(MemberSessionFailure) as error:
        await service.create(request())
    assert error.value.status == 503
    assert not connection.committed
    connection.execute.assert_not_called()


@pytest.mark.anyio
async def test_invalid_clock_fails_closed(passwords):
    _, _, connection, service = setup(passwords, clock=lambda: NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        await service.create(request())
    assert not connection.committed
