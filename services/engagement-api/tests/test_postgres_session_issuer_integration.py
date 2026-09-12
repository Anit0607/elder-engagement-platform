from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.member_auth import MemberRecord
from app.postgres_session_issuer import PostgresSessionIssuer

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASELINE = (
    Path(__file__).parents[3]
    / "database"
    / "migrations"
    / "V0001__engagement_baseline.sql"
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires the disposable PostgreSQL 16 test service"
)


@pytest.mark.anyio
async def test_real_postgres_persists_only_refresh_fingerprint():
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        await setup.execute(BASELINE.read_text(encoding="utf-8"))
    finally:
        await setup.close()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO engagement_app.app_users (
                  public_id, role, status, phone_e164, identity_provider_subject
                ) VALUES (
                  'AMI-SYNTHETIC-SESSION', 'member', 'active',
                  '+919999999901', 'synthetic-session-subject'
                )
                RETURNING id, role::text, status::text, created_at, updated_at
                """
            )
        member = MemberRecord(
            id=row["id"],
            role=row["role"],
            status=row["status"],
            display_name=None,
            preferred_language=None,
            profile_complete=False,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        issued = await PostgresSessionIssuer(
            pool,
            signing_key=b"integration-signing-material-32-bytes-minimum",
            refresh_pepper=b"integration-refresh-material-32-bytes-minimum",
            issuer="https://api.synthetic.example",
        ).issue(member, uuid4(), "android", None)
        async with pool.acquire() as connection:
            stored = await connection.fetchrow(
                """
                SELECT refresh_token_hash, expires_at > created_at AS valid_expiry
                  FROM engagement_app.auth_sessions
                 WHERE user_id = $1
                """,
                member.id,
            )
        assert stored["valid_expiry"] is True
        assert len(stored["refresh_token_hash"]) == 64
        assert issued.refresh_token not in stored["refresh_token_hash"]
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
