from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest

from app.member_auth import IdentityTokenRejected
from app.postgres_member_repository import PostgresMemberRepository

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
async def test_real_postgres_creates_one_member_under_concurrent_login():
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        await setup.execute(BASELINE.read_text(encoding="utf-8"))
    finally:
        await setup.close()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=6)
    try:
        repository = PostgresMemberRepository(pool)
        members = await asyncio.gather(
            *(
                repository.get_or_create_verified_member(
                    "+919999999901", "synthetic-concurrent-subject"
                )
                for _ in range(12)
            )
        )
        assert len({member.id for member in members}) == 1
        async with pool.acquire() as connection:
            count = await connection.fetchval(
                "SELECT count(*) FROM engagement_app.app_users"
            )
            assert count == 1

            await connection.execute(
                """
                INSERT INTO engagement_app.app_users (
                  public_id, role, status, phone_e164, identity_provider_subject
                ) VALUES (
                  'AMI-SYNTHETIC-SECOND', 'member', 'active',
                  '+919999999902', 'synthetic-second-subject'
                )
                """
            )
        with pytest.raises(IdentityTokenRejected):
            await repository.get_or_create_verified_member(
                "+919999999901", "synthetic-second-subject"
            )
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
