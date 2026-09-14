from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pyotp
import pytest
from pydantic import ValidationError

from app.authorization import Permission
from app.logging_config import redact, sanitize
from app.member_auth import MemberSessionFailure
from app.staff_credentials import (
    CredentialProtectionUnavailable,
    PasswordCapacityUnavailable,
    StaffAuthenticator,
    StaffPasswords,
)
from app.staff_enrollment import PostgresStaffEnrollment, StaffEnrollmentRequest

NOW = datetime(2026, 9, 15, 3, tzinfo=UTC)
PASSWORD = "synthetic-enrollment-password-only"  # noqa: S105 -- never a live credential
SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
CONFIRMATION = "BOOTSTRAP-FIRST-DEVELOPMENT-ADMINISTRATOR"


def request(role="contributor", **changes):
    values = dict(
        username="fictional.staff",
        password=PASSWORD,
        displayName="Fictional staff",
        preferredLanguage="en",
        role=role,
    )
    if role == "administrator":
        values.update(authenticatorSeed=SEED, authenticatorCode=pyotp.TOTP(SEED).at(NOW))
    values.update(changes)
    return StaffEnrollmentRequest(**values)


class Database:
    def __init__(self, *, exists=False, denied=False):
        self.execute = AsyncMock()
        self.fetchval = AsyncMock(return_value=exists)
        self.actor = uuid4()
        self.denied = denied
        self.committed = False
        self.commit_error = None
        self.permission = None

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self, token=None, permission=None):
        self.permission = permission
        if self.denied:
            raise MemberSessionFailure(status=403, code="FORBIDDEN", title="Denied")
        yield self if token is None else (self, SimpleNamespace(user_id=self.actor))
        if self.commit_error:
            raise self.commit_error
        self.committed = True


@pytest.fixture(scope="module")
def passwords():
    return StaffPasswords()


def service(database, passwords, *, now=lambda: NOW):
    return PostgresStaffEnrollment(
        database, database, passwords, StaffAuthenticator(bytes(range(32))), now=now
    )


async def bootstrap(handler, enrollment=None, **changes):
    values = dict(environment="development", confirmation=CONFIRMATION)
    values.update(changes)
    return await handler.bootstrap_development_administrator(
        enrollment or request("administrator"), "trace", **values
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "UPPERCASE"},
        {"username": "a b"},
        {"username": "ab"},
        {"username": 123},
        {"password": "short"},
        {"password": "x" * 257},
        {"displayName": " "},
        {"preferredLanguage": "fr"},
        {"role": "member"},
        {"passwordHash": "not-accepted"},
        {"authenticatorSeed": SEED},
        {"authenticatorCode": "123456"},
    ],
)
def test_reject_invalid_contributor_enrollment(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"authenticatorSeed": None},
        {"authenticatorCode": None},
        {"authenticatorSeed": "invalid"},
        {"authenticatorCode": "１２３４５６"},
        {"authenticatorCode": "12345678"},
    ],
)
def test_administrator_requires_valid_confirmation_shape(changes):
    with pytest.raises(ValidationError):
        request("administrator", **changes)


def test_request_repr_and_validation_message_do_not_expose_credentials():
    enrollment = request("administrator")
    assert PASSWORD not in repr(enrollment) and SEED not in repr(enrollment)
    with pytest.raises(ValidationError) as error:
        request(password=PASSWORD, username="UPPERCASE")
    assert PASSWORD not in str(error.value)


@pytest.mark.parametrize(
    "name", ["authenticatorSeed", "authenticator_seed", "authenticatorCode", "authenticator_code"]
)
def test_enrollment_secret_names_are_redacted(name):
    assert sanitize({name: "fictional-sensitive-value"}) == {name: "[REDACTED]"}
    assert "fictional-sensitive-value" not in redact(f'{name}="fictional-sensitive-value"')


@pytest.mark.anyio
async def test_contributor_is_created_only_under_administrator_authorization(passwords):
    db = Database()
    result = await service(db, passwords).create_contributor("fictional-session", request(), "trace")
    assert db.permission == Permission.CREATE_STAFF and db.committed
    assert result.role == "contributor" and result.status == "active"
    assert result.preferred_language == "en"
    calls = db.execute.await_args_list
    assert len(calls) == 4
    stored = calls[1].args
    assert passwords.verify(stored[2], PASSWORD)
    assert stored[3:] == (False, None, None)
    assert calls[-1].args[1] == db.actor
    assert PASSWORD not in repr(calls) and SEED not in repr(calls)
    assert "password" not in result.model_dump_json().lower()


@pytest.mark.anyio
async def test_non_administrator_cannot_create_contributor_or_hash_password(passwords, monkeypatch):
    db = Database(denied=True)
    monkeypatch.setattr(
        passwords, "hash", lambda value: pytest.fail("Permission denial must precede hashing")
    )
    with pytest.raises(MemberSessionFailure) as error:
        await service(db, passwords).create_contributor("fictional-session", request(), "trace")
    assert error.value.status == 403
    db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_contributor_route_cannot_create_administrator(passwords):
    db = Database()
    with pytest.raises(MemberSessionFailure) as error:
        await service(db, passwords).create_contributor(
            "fictional-session", request("administrator"), "trace"
        )
    assert error.value.status == 403 and db.permission is None
    db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_contributor_does_not_overwrite_credentials(passwords):
    db = Database()
    db.execute.side_effect = asyncpg.UniqueViolationError("private detail")
    with pytest.raises(MemberSessionFailure) as error:
        await service(db, passwords).create_contributor("fictional-session", request(), "trace")
    assert error.value.status == 409 and db.execute.await_count == 1 and not db.committed


@pytest.mark.anyio
async def test_failed_audit_rolls_back_entire_enrollment(passwords):
    db = Database()
    db.execute.side_effect = [None, None, None, None, asyncpg.PostgresError("private audit detail")]
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords))
    assert error.value.status == 503 and db.execute.await_count == 5 and not db.committed


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [{"environment": "production"}, {"confirmation": "wrong"}])
async def test_bootstrap_requires_controlled_development_operation(passwords, changes):
    db = Database()
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords), **changes)
    assert error.value.status == 403
    db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_bootstrap_refuses_contributor(passwords):
    db = Database()
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords), request())
    assert error.value.status == 400
    db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_bootstrap_confirms_encrypts_and_consumes_first_code(passwords):
    db = Database()
    result = await bootstrap(service(db, passwords))
    assert db.committed and result.role == "administrator"
    calls = db.execute.await_args_list
    assert "pg_advisory_xact_lock" in calls[0].args[0]
    assert len(calls) == 5
    credentials = calls[2].args
    assert credentials[1] == result.id and credentials[3] is True
    assert len(credentials[4]) == 60 and credentials[5] == int(NOW.timestamp()) // 30
    assert (
        StaffAuthenticator(bytes(range(32))).matched_step(
            result.id, credentials[4], pyotp.TOTP(SEED).at(NOW), NOW, credentials[5]
        )
        is None
    )
    assert calls[-1].args[1] is None
    assert PASSWORD not in repr(calls) and SEED not in repr(calls)


@pytest.mark.anyio
async def test_bootstrap_never_overwrites_existing_administrator(passwords):
    db = Database(exists=True)
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords))
    assert error.value.status == 409 and not db.committed
    assert db.execute.await_count == 1


@pytest.mark.anyio
async def test_wrong_authenticator_code_creates_no_account(passwords):
    db = Database()
    wrong = f"{(int(pyotp.TOTP(SEED).at(NOW)) + 1) % 1000000:06d}"
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords), request("administrator", authenticatorCode=wrong))
    assert error.value.status == 401 and not db.committed
    assert db.execute.await_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,status", [(PasswordCapacityUnavailable, 429), (CredentialProtectionUnavailable, 503)]
)
async def test_protection_failure_creates_no_account(passwords, monkeypatch, kind, status):
    db = Database()

    def fail(value):
        raise kind()

    monkeypatch.setattr(passwords, "hash", fail)
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords))
    assert error.value.status == status and db.execute.await_count == 1 and not db.committed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,status",
    [(asyncpg.UniqueViolationError, 409), (asyncpg.PostgresError, 503), (OSError, 503), (TimeoutError, 503)],
)
async def test_database_failure_is_not_retried(passwords, kind, status):
    db = Database()
    db.execute.side_effect = [None, kind("private detail")]
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords))
    assert error.value.status == status and db.execute.await_count == 2 and not db.committed
    assert "private detail" not in error.value.title


@pytest.mark.anyio
async def test_uncertain_commit_does_not_trigger_second_bootstrap(passwords):
    db = Database()
    db.commit_error = OSError("private detail")
    with pytest.raises(MemberSessionFailure) as error:
        await bootstrap(service(db, passwords))
    assert error.value.status == 503 and error.value.retryable is False
    assert db.fetchval.await_count == 1 and db.execute.await_count == 5


@pytest.mark.anyio
async def test_timezone_unaware_clock_is_rejected_before_account_write(passwords):
    db = Database()
    with pytest.raises(ValueError):
        await bootstrap(service(db, passwords, now=lambda: NOW.replace(tzinfo=None)))
    assert db.execute.await_count == 1 and not db.committed
