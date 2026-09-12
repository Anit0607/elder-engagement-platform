from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import jwt
import pytest

from app.member_auth import MemberRecord, MemberSessionFailure
from app.session_controls import PostgresSessionControls

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASELINE = Path(__file__).parents[3] / "database" / "migrations" / "V0001__engagement_baseline.sql"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")


@pytest.mark.anyio
async def test_real_postgres_owner_isolation_suspension_expiry_and_logout():
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        await setup.execute(BASELINE.read_text(encoding="utf-8"))
    finally:
        await setup.close()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    key = b"integration-signing-material-at-least-32-bytes"
    controls = PostgresSessionControls(
        pool, signing_key=key, refresh_pepper=b"integration-refresh-material-at-least-32-bytes",
        issuer="https://api.synthetic.example",
        member_session_limit=5,
    )
    try:
        members = []
        async with pool.acquire() as connection:
            for index in range(2):
                row = await connection.fetchrow(
                    """INSERT INTO engagement_app.app_users
                       (public_id, role, status, identity_provider_subject)
                       VALUES ($1, 'member', 'active', $2) RETURNING id, created_at, updated_at""",
                    f"AMI-SYNTHETIC-CONTROLS-{index}", f"synthetic-controls-subject-{index}",
                )
                members.append(MemberRecord(id=row["id"], role="member", status="active",
                                            display_name=None, preferred_language=None,
                                            profile_complete=False,
                                            created_at=row["created_at"], updated_at=row["updated_at"]))
        first = await controls.issue(members[0], uuid4(), "android", None)
        second = await controls.issue(members[0], uuid4(), "ios", "Synthetic device")
        foreign = await controls.issue(members[1], uuid4(), "android", None)
        claims = jwt.decode(foreign.access_token, key, algorithms=["HS256"], audience="amiko-api")
        with pytest.raises(MemberSessionFailure) as error:
            await controls.revoke(first.access_token, UUID(claims["sid"]))
        assert error.value.status == 404
        assert len(await controls.list_sessions(first.access_token)) == 2
        assert len(await controls.list_sessions(foreign.access_token)) == 1
        second_id = next(
            row.id for row in await controls.list_sessions(first.access_token) if not row.current
        )
        await controls.revoke(first.access_token, second_id)
        with pytest.raises(MemberSessionFailure) as error:
            await controls.list_sessions(second.access_token)
        assert error.value.status == 401
        assert len(await controls.list_sessions(first.access_token)) == 1
        async with pool.acquire() as connection:
            await connection.execute("UPDATE engagement_app.app_users SET status='suspended' WHERE id=$1",
                                     members[0].id)
        with pytest.raises(MemberSessionFailure) as error:
            await controls.list_sessions(first.access_token)
        assert error.value.status == 403
        async with pool.acquire() as connection:
            await connection.execute("UPDATE engagement_app.app_users SET status='active' WHERE id=$1",
                                     members[0].id)
        outcomes = await asyncio.gather(
            controls.logout(first.access_token), controls.logout(first.access_token), return_exceptions=True,
        )
        assert sum(result is None for result in outcomes) == 1
        rejected = next(result for result in outcomes if result is not None)
        assert isinstance(rejected, MemberSessionFailure)
        assert rejected.status == 401
        attempts = await asyncio.gather(
            *(controls.issue(members[0], uuid4(), "android", None) for _ in range(6)),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in attempts) == 3
        limits = [result for result in attempts if isinstance(result, MemberSessionFailure)]
        assert len(limits) == 3
        assert all(result.status == 429 for result in limits)
        with pytest.raises(MemberSessionFailure) as error:
            await controls.list_sessions(first.access_token)
        assert error.value.status == 401
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE engagement_app.auth_sessions
                    SET created_at=now()-interval '2 days', expires_at=now()-interval '1 day'
                    WHERE user_id=$1""", members[1].id,
            )
        with pytest.raises(MemberSessionFailure) as error:
            await controls.list_sessions(foreign.access_token)
        assert error.value.status == 401
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
