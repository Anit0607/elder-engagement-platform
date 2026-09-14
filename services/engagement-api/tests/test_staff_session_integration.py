"""Only GitHub's disposable PostgreSQL is accepted, never a client database."""

from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import jwt
import pyotp
import pytest

from app.config import ConfigurationError
from app.member_auth import MemberSessionFailure
from app.postgres_staff_session import PostgresStaffSessionService
from app.session_refresh import PostgresSessionRefresh
from app.shared_session_controls import SharedSessionControls
from app.staff_auth import StaffSessionRequest
from app.staff_credentials import StaffAuthenticator, StaffCredentialVerifier, StaffPasswords
from app.staff_schema import verify_staff_schema
from app.staff_session_controls import PostgresStaffSessionControls

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).parents[3] / "database" / "migrations"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")
PASSWORD = "non-working-staff-database-fixture"  # noqa: S105 -- disposable tests only
SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
KEY = b"database-only-staff-signing-material-32-bytes"
PEPPER = b"database-only-staff-refresh-material-32-bytes"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def staff_db(anyio_backend):
    target = urlsplit(DATABASE_URL)
    if target.hostname not in {"localhost", "127.0.0.1"} or target.path != "/postgres":
        raise RuntimeError("Refusing to modify anything except the disposable PostgreSQL test database")
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        assert int(await setup.fetchval("SHOW server_version_num")) // 10000 == 16
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        for filename in (
            "V0001__engagement_baseline.sql",
            "V0002__staff_authentication.sql",
            "V0003__role_change_session_revocation.sql",
        ):
            await setup.execute((MIGRATIONS / filename).read_text(encoding="utf-8"))
    finally:
        await setup.close()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()


async def account(pool, role="contributor", enabled=False):
    passwords = StaffPasswords()
    authenticator = StaffAuthenticator(bytes(range(32)))
    username = f"synthetic-{uuid4()}"
    async with pool.acquire() as connection:
        owner = await connection.fetchval(
            """INSERT INTO engagement_app.app_users (public_id, role, status, username)
               VALUES ($1,$2,'active',$3) RETURNING id""",
            f"AMI-SYN-{uuid4().hex[:16]}",
            role,
            username,
        )
        await connection.execute(
            """INSERT INTO engagement_app.staff_credentials
               (user_id, password_hash, second_factor_enabled, mfa_secret_ciphertext)
               VALUES ($1,$2,$3,$4)""",
            owner,
            passwords.hash(PASSWORD),
            enabled,
            authenticator.protect(owner, SEED) if enabled else None,
        )
    # Fixed time avoids a rare random adjacent-code collision changing assertions.
    clock = [datetime(2026, 9, 14, 5, 0, tzinfo=UTC)]

    def service():
        return PostgresStaffSessionService(
            pool,
            verifier=StaffCredentialVerifier(passwords, authenticator),
            signing_key=KEY,
            refresh_pepper=PEPPER,
            issuer="https://api.synthetic.example",
            now=lambda: clock[0],
        )

    def request(**kwargs):
        values = {"username": username, "password": PASSWORD, "installationId": uuid4(), "platform": "web"}
        values.update(kwargs)
        return StaffSessionRequest(**values)

    return owner, service, request, clock, passwords, authenticator


@pytest.mark.anyio
async def test_runtime_metadata_gate_with_application_permissions_and_no_ledger(staff_db):
    role = "synthetic_runtime_" + uuid4().hex
    async with staff_db.acquire() as connection:
        await connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
        try:
            await connection.execute(f'GRANT USAGE ON SCHEMA engagement_app TO "{role}"')
            await connection.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA engagement_app TO "{role}"')

            class RuntimePool:
                @asynccontextmanager
                async def acquire(self):
                    async with connection.transaction():
                        await connection.execute(f'SET LOCAL ROLE "{role}"')
                        yield connection

            # The application cannot access the update ledger; it is not even
            # present in this fixture. Metadata must still prove staff readiness.
            await verify_staff_schema(RuntimePool())
            await connection.execute(
                "ALTER TABLE engagement_app.app_users DISABLE TRIGGER app_users_session_role_guard"
            )
            with pytest.raises(ConfigurationError):
                await verify_staff_schema(RuntimePool())
            await connection.execute(
                "ALTER TABLE engagement_app.app_users ENABLE TRIGGER app_users_session_role_guard"
            )
            await verify_staff_schema(RuntimePool())
        finally:
            await connection.execute(f'DROP OWNED BY "{role}"')
            await connection.execute(f'DROP ROLE "{role}"')


@pytest.mark.anyio
async def test_shared_endpoint_adapter_preserves_staff_role_and_logout(staff_db):
    _, service, request, clock, _, _ = await account(staff_db)
    # This scenario also verifies real JWT expiry; unlike the TOTP replay
    # fixtures above, its issuance clock must match the verifier's wall clock.
    clock[0] = datetime.now(UTC)
    result = await service().create(request())
    options = dict(
        signing_key=KEY, refresh_pepper=PEPPER, issuer="https://api.synthetic.example", now=lambda: clock[0]
    )
    shared = SharedSessionControls(
        staff_db,
        PostgresSessionRefresh(staff_db, **options),
        PostgresStaffSessionControls(staff_db, **options),
        PEPPER,
    )
    assert len(await shared.list_sessions(result.access_token)) == 1
    renewed = await shared.refresh(result.refresh_token)
    assert renewed.user.role == "contributor"
    await shared.logout(renewed.access_token)
    with pytest.raises(MemberSessionFailure) as error:
        await shared.list_sessions(renewed.access_token)
    assert error.value.status == 401


@pytest.mark.anyio
async def test_persistent_failed_attempts_lock_and_unlock_across_service_instances(staff_db):
    owner, service, request, clock, _, _ = await account(staff_db)
    for _ in range(5):
        with pytest.raises(MemberSessionFailure) as error:
            await service().create(request(password=PASSWORD + "-wrong"))
        assert error.value.status == 401
    async with staff_db.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert row["failed_attempts"] == 5
        assert row["locked_until"] == clock[0] + timedelta(minutes=10)
        assert await connection.fetchval("SELECT count(*) FROM engagement_app.auth_sessions") == 0
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(request())
    assert error.value.status == 429
    clock[0] += timedelta(minutes=10, seconds=1)
    result = await service().create(request())
    assert result.user.role == "contributor"
    async with staff_db.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert (row["failed_attempts"], row["locked_until"]) == (0, None)
        saved = await connection.fetchrow(
            "SELECT * FROM engagement_app.auth_sessions WHERE user_id=$1", owner
        )
        assert (
            saved["refresh_token_hash"] == hmac.digest(PEPPER, result.refresh_token.encode(), "sha256").hex()
        )
        assert saved["staff_credential_version"] == row["credential_version"]


@pytest.mark.anyio
async def test_parallel_administrator_code_has_exactly_one_success(staff_db):
    owner, service, request, clock, _, _ = await account(staff_db, "administrator", True)
    code = pyotp.TOTP(SEED).at(clock[0])
    results = await asyncio.gather(
        *(service().create(request(secondFactorCode=code)) for _ in range(2)), return_exceptions=True
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    rejected = next(result for result in results if isinstance(result, Exception))
    assert isinstance(rejected, MemberSessionFailure) and rejected.status == 401
    async with staff_db.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert row["last_accepted_totp_step"] == int(clock[0].timestamp()) // 30
        assert row["failed_attempts"] == 1
        assert await connection.fetchval("SELECT count(*) FROM engagement_app.auth_sessions") == 1
    clock[0] += timedelta(seconds=30)
    await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))


@pytest.mark.anyio
async def test_insert_failure_rolls_back_code_consumption(staff_db):
    owner, service, request, clock, _, _ = await account(staff_db, "administrator", True)
    async with staff_db.acquire() as connection:
        await connection.execute("""ALTER TABLE engagement_app.auth_sessions
                                    ADD CONSTRAINT synthetic_insert_failure CHECK (false)""")
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    assert (error.value.status, error.value.retryable) == (503, False)
    async with staff_db.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert row["last_accepted_totp_step"] is None
        assert await connection.fetchval("SELECT count(*) FROM engagement_app.auth_sessions") == 0
        await connection.execute(
            "ALTER TABLE engagement_app.auth_sessions DROP CONSTRAINT synthetic_insert_failure"
        )
    await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))


@pytest.mark.anyio
async def test_password_change_revokes_sessions_without_resetting_used_code(staff_db):
    owner, service, request, clock, passwords, _ = await account(staff_db, "administrator", True)
    await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    async with staff_db.acquire() as connection:
        before = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        async with connection.transaction():
            await connection.fetchval("SELECT id FROM engagement_app.app_users WHERE id=$1 FOR UPDATE", owner)
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET password_hash=$2 WHERE user_id=$1",
                owner,
                passwords.hash(PASSWORD + "-changed"),
            )
        after = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert after["credential_version"] != before["credential_version"]
        assert after["last_accepted_totp_step"] == before["last_accepted_totp_step"]
        assert await connection.fetchval(
            "SELECT bool_and(revoked_at IS NOT NULL) FROM engagement_app.auth_sessions"
        )
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    assert error.value.status == 401
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(
            request(password=PASSWORD + "-changed", secondFactorCode=pyotp.TOTP(SEED).at(clock[0]))
        )
    assert error.value.status == 401
    clock[0] += timedelta(seconds=30)
    await service().create(
        request(password=PASSWORD + "-changed", secondFactorCode=pyotp.TOTP(SEED).at(clock[0]))
    )


@pytest.mark.anyio
async def test_authenticator_replacement_and_database_guards(staff_db):
    owner, service, request, clock, _, authenticator = await account(staff_db, "administrator", True)
    await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    async with staff_db.acquire() as connection:
        with pytest.raises(asyncpg.RaiseError):
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET last_accepted_totp_step=NULL WHERE user_id=$1",
                owner,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET mfa_secret_ciphertext=$2 WHERE user_id=$1",
                owner,
                b"invalid",
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET mfa_secret_ciphertext=NULL WHERE user_id=$1",
                owner,
            )
        new_seed = authenticator.new_seed()
        await connection.execute(
            "UPDATE engagement_app.staff_credentials SET mfa_secret_ciphertext=$2 WHERE user_id=$1",
            owner,
            authenticator.protect(owner, new_seed),
        )
        row = await connection.fetchrow(
            "SELECT * FROM engagement_app.staff_credentials WHERE user_id=$1", owner
        )
        assert row["last_accepted_totp_step"] is None
        assert await connection.fetchval(
            "SELECT bool_and(revoked_at IS NOT NULL) FROM engagement_app.auth_sessions"
        )
    await service().create(request(secondFactorCode=pyotp.TOTP(new_seed).at(clock[0])))


@pytest.mark.anyio
async def test_suspension_admin_requires_authenticator_and_session_limit(staff_db):
    owner, service, request, _, _, _ = await account(staff_db)
    results = await asyncio.gather(*(service().create(request()) for _ in range(6)), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 5
    assert next(result for result in results if isinstance(result, MemberSessionFailure)).status == 429
    async with staff_db.acquire() as connection:
        await connection.execute("UPDATE engagement_app.app_users SET status='suspended' WHERE id=$1", owner)
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(request())
    assert error.value.status == 403
    _, admin_service, admin_request, _, _, _ = await account(staff_db, "administrator", False)
    with pytest.raises(MemberSessionFailure) as error:
        await admin_service().create(admin_request())
    assert error.value.status == 503


@pytest.mark.anyio
async def test_authoritative_role_and_password_change_wait_for_login_transaction(staff_db):
    owner, service, request, _, passwords, _ = await account(staff_db)
    async with staff_db.acquire() as connection:
        async with connection.transaction():
            await connection.fetchval("SELECT id FROM engagement_app.app_users WHERE id=$1 FOR UPDATE", owner)
            pending = asyncio.create_task(service().create(request()))
            await asyncio.sleep(0.05)
            assert not pending.done()
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET password_hash=$2 WHERE user_id=$1",
                owner,
                passwords.hash(PASSWORD + "-changed"),
            )
        with pytest.raises(MemberSessionFailure) as error:
            await pending
        assert error.value.status == 401
        assert await connection.fetchval("SELECT count(*) FROM engagement_app.auth_sessions") == 0
        await connection.execute(
            "UPDATE engagement_app.app_users SET role='administrator' WHERE id=$1", owner
        )
    with pytest.raises(MemberSessionFailure) as error:
        await service().create(request(password=PASSWORD + "-changed"))
    assert error.value.status == 503


@pytest.mark.anyio
async def test_staff_token_cannot_be_used_as_member_token(staff_db):
    from app.session_controls import PostgresSessionControls

    _, service, request, _, _, _ = await account(staff_db)
    result = await service().create(request())
    claims = jwt.decode(
        result.access_token,
        KEY,
        algorithms=["HS256"],
        audience="amiko-api",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert claims["role"] == "contributor"
    controls = PostgresSessionControls(
        staff_db, signing_key=KEY, refresh_pepper=PEPPER, issuer="https://api.synthetic.example"
    )
    with pytest.raises(MemberSessionFailure) as error:
        await controls.list_sessions(result.access_token)
    assert error.value.status == 401


def staff_controls(pool, clock, monkeypatch):
    from app.staff_session_controls import PostgresStaffSessionControls

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    return PostgresStaffSessionControls(
        pool,
        signing_key=KEY,
        refresh_pepper=PEPPER,
        issuer="https://api.synthetic.example",
        now=lambda: clock[0],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("role,enabled", [("contributor", False), ("administrator", True)])
async def test_staff_refresh_owner_isolation_and_logout(staff_db, monkeypatch, role, enabled):
    _, service, request, clock, _, _ = await account(staff_db, role, enabled)
    controls = staff_controls(staff_db, clock, monkeypatch)
    code = pyotp.TOTP(SEED).at(clock[0]) if enabled else None
    first = await service().create(request(secondFactorCode=code))
    _, foreign_service, foreign_request, _, _, _ = await account(staff_db)
    foreign = await foreign_service().create(foreign_request())
    foreign_id = controls._claims(foreign.access_token)[1]
    with pytest.raises(MemberSessionFailure) as error:
        await controls.revoke(first.access_token, foreign_id)
    assert error.value.status == 404
    assert len(await controls.list_sessions(first.access_token)) == 1
    clock[0] += timedelta(minutes=11)
    with pytest.raises(MemberSessionFailure):
        await controls.list_sessions(first.access_token)
    refreshed = await controls.refresh(first.refresh_token)
    assert refreshed.user.role == role
    assert len(await controls.list_sessions(refreshed.access_token)) == 1
    async with staff_db.acquire() as connection:
        expiries = await connection.fetch(
            "SELECT expires_at FROM engagement_app.auth_sessions WHERE user_id=$1", refreshed.user.id
        )
        assert len({row["expires_at"] for row in expiries}) == 1
    await controls.logout(refreshed.access_token)
    with pytest.raises(MemberSessionFailure):
        await controls.refresh(refreshed.refresh_token)


@pytest.mark.anyio
async def test_staff_refresh_replay_and_role_promotion_never_gain_privilege(staff_db, monkeypatch):
    owner, service, request, clock, _, _ = await account(staff_db, "contributor", True)
    controls = staff_controls(staff_db, clock, monkeypatch)
    first = await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    results = await asyncio.gather(
        *(controls.refresh(first.refresh_token) for _ in range(2)), return_exceptions=True
    )
    refreshed = next(result for result in results if not isinstance(result, Exception))
    error = next(result for result in results if isinstance(result, MemberSessionFailure))
    assert error.code == "REFRESH_TOKEN_REUSED"
    with pytest.raises(MemberSessionFailure):
        await controls.refresh(refreshed.refresh_token)
    clock[0] += timedelta(seconds=30)
    second = await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    async with staff_db.acquire() as connection:
        await connection.execute(
            "UPDATE engagement_app.app_users SET role='administrator' WHERE id=$1", owner
        )
        assert await connection.fetchval(
            "SELECT bool_and(revoked_at IS NOT NULL) FROM engagement_app.auth_sessions WHERE user_id=$1",
            owner,
        )
    with pytest.raises(MemberSessionFailure):
        await controls.refresh(second.refresh_token)
    with pytest.raises(MemberSessionFailure):
        await controls.list_sessions(second.access_token)
    clock[0] += timedelta(seconds=30)
    admin = await service().create(request(secondFactorCode=pyotp.TOTP(SEED).at(clock[0])))
    assert (await controls.refresh(admin.refresh_token)).user.role == "administrator"


@pytest.mark.anyio
async def test_staff_current_credential_and_suspension_checks(staff_db, monkeypatch):
    owner, service, request, clock, passwords, _ = await account(staff_db)
    controls = staff_controls(staff_db, clock, monkeypatch)
    first = await service().create(request())
    async with staff_db.acquire() as connection:
        await connection.execute("UPDATE engagement_app.app_users SET status='suspended' WHERE id=$1", owner)
    for operation in (
        lambda: controls.refresh(first.refresh_token),
        lambda: controls.logout(first.access_token),
    ):
        with pytest.raises(MemberSessionFailure) as error:
            await operation()
        assert error.value.status == 403
    async with staff_db.acquire() as connection:
        await connection.execute("UPDATE engagement_app.app_users SET status='active' WHERE id=$1", owner)
        async with connection.transaction():
            await connection.fetchval("SELECT id FROM engagement_app.app_users WHERE id=$1 FOR UPDATE", owner)
            await connection.execute(
                "UPDATE engagement_app.staff_credentials SET password_hash=$2 WHERE user_id=$1",
                owner,
                passwords.hash(PASSWORD + "-changed"),
            )
    with pytest.raises(MemberSessionFailure):
        await controls.list_sessions(first.access_token)
    with pytest.raises(MemberSessionFailure):
        await controls.refresh(first.refresh_token)
