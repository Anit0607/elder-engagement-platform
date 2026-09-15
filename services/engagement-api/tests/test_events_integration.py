"""Event visibility against GitHub's disposable PostgreSQL 16 only."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

from app.authorization import Permission, Principal
from app.events import EventCreate, PostgresEventService

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).parents[3] / "database" / "migrations"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")


class DirectAuthorization:
    def __init__(self, pool, identities):
        self.pool, self.identities = pool, identities

    def _proof(self, token):
        user_id, role = self.identities[token]
        return user_id, uuid4(), role, None

    @asynccontextmanager
    async def transaction(self, token, permission, *, target=None):
        user_id, role = self.identities[token]
        if permission == Permission.MANAGE_EVENTS:
            assert role == "administrator"
        elif permission == Permission.VIEW_EVENTS:
            assert role == "member" and target == user_id
        else:
            raise AssertionError("Unexpected permission")
        async with self.pool.acquire() as connection, connection.transaction():
            yield connection, Principal(user_id, uuid4(), role)


async def prepare_database():
    target = urlsplit(DATABASE_URL)
    if target.hostname not in {"localhost", "127.0.0.1"} or target.path != "/postgres":
        raise RuntimeError("Refusing to modify anything except the disposable PostgreSQL test database")
    setup = await asyncpg.connect(DATABASE_URL)
    try:
        assert int(await setup.fetchval("SHOW server_version_num")) // 10000 == 16
        await setup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        await setup.execute("CREATE SCHEMA engagement_app")
        await setup.execute("SET search_path TO engagement_app, pg_catalog")
        await setup.execute(
            (MIGRATIONS / "V0001__engagement_baseline.sql").read_text(encoding="utf-8")
        )
        await setup.execute(
            (MIGRATIONS / "V0009__event_reminder_rules.sql").read_text(encoding="utf-8")
        )
    finally:
        await setup.close()


@pytest.mark.anyio
async def test_real_postgres_event_creation_and_circle_visibility():
    await prepare_database()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    try:
        async with pool.acquire() as connection:
            administrator = await connection.fetchval(
                """INSERT INTO engagement_app.app_users (public_id,role,status,username)
                   VALUES($1,'administrator','active',$2) RETURNING id""",
                f"AMI-ADM-{uuid4().hex[:16]}",
                f"synthetic-event-admin-{uuid4().hex[:12]}",
            )
            members = []
            for index in range(2):
                members.append(
                    await connection.fetchval(
                        """INSERT INTO engagement_app.app_users
                           (public_id,role,status,identity_provider_subject)
                           VALUES($1,'member','active',$2) RETURNING id""",
                        f"AMI-MEM-{uuid4().hex[:16]}",
                        f"synthetic-event-member-{index}-{uuid4()}",
                    )
                )
            circle = await connection.fetchval(
                """INSERT INTO engagement_app.circles (name,created_by)
                   VALUES($1,$2) RETURNING id""",
                f"Synthetic event circle {uuid4().hex[:8]}",
                administrator,
            )
            await connection.execute(
                """INSERT INTO engagement_app.circle_memberships
                   (circle_id,user_id) VALUES($1,$2)""",
                circle,
                members[0],
            )
        service = PostgresEventService(
            DirectAuthorization(
                pool,
                {
                    "administrator": (administrator, "administrator"),
                    "member-one": (members[0], "member"),
                    "member-two": (members[1], "member"),
                },
            )
        )
        start = datetime.now(UTC) + timedelta(days=2)
        created = await service.create(
            "administrator",
            EventCreate(
                title="Synthetic circle event",
                startsAt=start,
                endsAt=start + timedelta(hours=1),
                audience="circles",
                circleIds=[circle],
                reminderMinutesBefore=[1440, 60],
            ),
            "synthetic-event-create",
        )
        assert created.circle_ids == [circle]
        assert created.reminder_minutes_before == [1440, 60]
        visible = await service.list_visible("member-one", "upcoming", 20, None)
        assert [item.id for item in visible.items] == [created.id]
        assert (await service.list_visible("member-two", "upcoming", 20, None)).items == []

        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE engagement_app.circle_memberships
                   SET left_at=now() WHERE circle_id=$1 AND user_id=$2""",
                circle,
                members[0],
            )
        assert (await service.list_visible("member-one", "upcoming", 20, None)).items == []
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
