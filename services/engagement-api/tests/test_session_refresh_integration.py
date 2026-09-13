from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import jwt
import pytest

from app.member_auth import MemberRecord, MemberSessionFailure
from app.session_refresh import PostgresSessionRefresh

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASELINE = Path(__file__).parents[3] / "database" / "migrations" / "V0001__engagement_baseline.sql"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")


@pytest.mark.anyio
async def test_real_postgres_rotation_replay_concurrency_logout_and_login_limit():
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        await setup.execute(BASELINE.read_text(encoding="utf-8"))
    finally:
        await setup.close()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    key = b"integration-signing-material-at-least-32-bytes"
    controls = PostgresSessionRefresh(
        pool, signing_key=key, refresh_pepper=b"integration-refresh-material-at-least-32-bytes",
        issuer="https://api.synthetic.example", member_session_limit=5,
    )

    async def rejects(operation, code):
        with pytest.raises(MemberSessionFailure) as error:
            await operation
        assert error.value.code == code

    try:
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """INSERT INTO engagement_app.app_users
                   (public_id, role, status, identity_provider_subject)
                   VALUES ('AMI-SYNTHETIC-REFRESH', 'member', 'active', 'synthetic-refresh-subject')
                   RETURNING id, created_at, updated_at""",
            )
        member = MemberRecord(id=row["id"], role="member", status="active", display_name=None,
                              preferred_language=None, profile_complete=False,
                              created_at=row["created_at"], updated_at=row["updated_at"])
        installation = uuid4()
        original = await controls.issue(member, installation, "android", "Synthetic device")
        current = original
        original_id = UUID(jwt.decode(original.access_token, key, algorithms=["HS256"],
                                      audience="amiko-api")["sid"])
        for _ in range(6):
            refreshed = await controls.refresh(current.refresh_token)
            await rejects(controls.list_sessions(current.access_token), "AUTHENTICATION_FAILED")
            assert refreshed.user.id == member.id
            assert len(await controls.list_sessions(refreshed.access_token)) == 1
            assert refreshed.refresh_token != current.refresh_token
            current = refreshed
        async with pool.acquire() as connection:
            sessions = await connection.fetch("SELECT * FROM engagement_app.auth_sessions WHERE user_id=$1",
                                              member.id)
        root = next(session for session in sessions if session["id"] == original_id)
        assert len(sessions) == 7
        assert all(session["token_family_id"] == root["token_family_id"] for session in sessions)
        assert all(session["expires_at"] == root["expires_at"] for session in sessions)
        assert all(session["installation_id"] == installation for session in sessions)
        assert all(session["refresh_token_hash"] != current.refresh_token for session in sessions)
        # Six renewals do not consume the five fresh-login allowance.
        second = await controls.issue(member, uuid4(), "ios", None)
        await rejects(controls.refresh(original.refresh_token), "REFRESH_TOKEN_REUSED")
        await rejects(controls.refresh(current.refresh_token), "SESSION_REVOKED")
        await rejects(controls.list_sessions(current.access_token), "AUTHENTICATION_FAILED")
        assert len(await controls.list_sessions(second.access_token)) == 1
        async with pool.acquire() as connection:
            family = await connection.fetch(
                "SELECT revoked_at FROM engagement_app.auth_sessions WHERE token_family_id=$1",
                root["token_family_id"],
            )
        assert all(session["revoked_at"] is not None for session in family)
        outcomes = await asyncio.gather(controls.refresh(second.refresh_token),
                                        controls.refresh(second.refresh_token), return_exceptions=True)
        success = [result for result in outcomes if not isinstance(result, Exception)]
        failures = [result for result in outcomes if isinstance(result, MemberSessionFailure)]
        assert len(success) == len(failures) == 1
        assert failures[0].code == "REFRESH_TOKEN_REUSED"
        await rejects(controls.refresh(success[0].refresh_token), "SESSION_REVOKED")
        third = await controls.issue(member, uuid4(), "android", None)
        await controls.logout(third.access_token)
        await rejects(controls.refresh(third.refresh_token), "SESSION_REVOKED")
        fourth = await controls.issue(member, uuid4(), "android", None)
        outcomes = await asyncio.gather(controls.logout(fourth.access_token),
                                        controls.refresh(fourth.refresh_token), return_exceptions=True)
        # Whichever obtains the user lock first invalidates the other credential.
        assert sum(not isinstance(result, Exception) for result in outcomes) == 1
        renewed = next((result for result in outcomes if result is not None
                        and not isinstance(result, Exception)), None)
        if renewed:
            await controls.logout(renewed.access_token)
            await rejects(controls.refresh(renewed.refresh_token), "SESSION_REVOKED")
        fifth = await controls.issue(member, uuid4(), "android", None)
        await rejects(controls.issue(member, uuid4(), "android", None), "RATE_LIMITED")
        async with pool.acquire() as connection:
            await connection.execute("UPDATE engagement_app.app_users SET status='suspended' WHERE id=$1",
                                     member.id)
        await rejects(controls.refresh(fifth.refresh_token), "ACCOUNT_SUSPENDED")
        async with pool.acquire() as connection:
            await connection.execute("UPDATE engagement_app.app_users SET status='active' WHERE id=$1",
                                     member.id)
            await connection.execute(
                """UPDATE engagement_app.auth_sessions
                   SET created_at=now()-interval '2 days', expires_at=now()-interval '1 day'
                   WHERE user_id=$1""", member.id,
            )
        await rejects(controls.refresh(fifth.refresh_token), "INVALID_REFRESH_TOKEN")
        assert datetime.now(UTC) > root["created_at"]
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
