"""Circle behaviour against GitHub's disposable PostgreSQL 16 only."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

from app.authorization import Permission, Principal
from app.circles import CircleCreate, CircleSettingsUpdate, CircleUpdate
from app.member_auth import MemberSessionFailure
from app.postgres_circles import PostgresCircleService, verify_circle_schema

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).parents[3] / "database" / "migrations"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")


class DirectAuthorization:
    def __init__(self, pool, identities):
        self.pool = pool
        self.identities = identities

    def _proof(self, token):
        user_id, role = self.identities[token]
        return user_id, uuid4(), role, None

    @asynccontextmanager
    async def transaction(self, token, permission, *, target=None):
        user_id, role = self.identities[token]
        if permission in {Permission.MANAGE_CIRCLES, Permission.MANAGE_CIRCLE_MEMBERSHIPS}:
            assert role == "administrator"
        elif permission == Permission.OWN_CIRCLE_MEMBERSHIPS:
            assert role == "member" and target == user_id
        elif permission == Permission.VIEW_CIRCLES:
            assert target == user_id
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
        await setup.execute((MIGRATIONS / "V0001__engagement_baseline.sql").read_text(encoding="utf-8"))
        await setup.execute(
            (MIGRATIONS / "V0006__circle_membership_configuration.sql").read_text(encoding="utf-8")
        )
    finally:
        await setup.close()


@pytest.mark.anyio
async def test_real_postgres_circle_suggestions_membership_limit_and_administration():
    await prepare_database()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    try:
        await verify_circle_schema(pool)
        async with pool.acquire() as connection:
            administrator = await connection.fetchval(
                """INSERT INTO engagement_app.app_users (public_id,role,status)
                   VALUES($1,'administrator','active') RETURNING id""",
                f"AMI-ADM-{uuid4().hex[:16]}",
            )
            member = await connection.fetchval(
                """INSERT INTO engagement_app.app_users
                   (public_id,role,status,identity_provider_subject)
                   VALUES($1,'member','active',$2) RETURNING id""",
                f"AMI-MEM-{uuid4().hex[:16]}",
                f"synthetic-circle-member-{uuid4()}",
            )
            await connection.execute(
                """INSERT INTO engagement_app.user_profiles
                   (user_id,display_name,preferred_language,interests,profile_complete)
                   VALUES($1,'Synthetic Circle Member','bn',$2,true)""",
                member,
                ["Music"],
            )
        service = PostgresCircleService(
            DirectAuthorization(
                pool, {"administrator": (administrator, "administrator"), "member": (member, "member")}
            )
        )
        circles = []
        for index in range(6):
            rules = {"interests": ["Music"]} if index == 0 else {"preferredLanguages": ["hi"]}
            circles.append(
                await service.create(
                    "administrator",
                    CircleCreate(name=f"Synthetic circle {index + 1}", suggestionRules=rules),
                    f"synthetic-create-{index}",
                )
            )
        with pytest.raises(MemberSessionFailure) as duplicate:
            await service.create(
                "administrator",
                CircleCreate(name="SYNTHETIC CIRCLE 1"),
                "synthetic-duplicate-name",
            )
        assert (duplicate.value.status, duplicate.value.code) == (409, "CONFLICT")
        listed = await service.list_mine("member")
        assert len(listed) == 6
        assert listed[0].suggested
        assert sum(circle.suggested for circle in listed) == 1

        for circle in circles[:5]:
            await service.join("member", circle.id, "synthetic-member-join")
        with pytest.raises(MemberSessionFailure) as error:
            await service.join("member", circles[5].id, "synthetic-over-limit")
        assert (error.value.status, error.value.code) == (409, "CIRCLE_LIMIT_REACHED")

        await service.leave("member", circles[0].id, "synthetic-member-leave")
        await service.assign("administrator", member, circles[5].id, "synthetic-administrator-assignment")
        listed = await service.list_mine("member")
        assigned = next(circle for circle in listed if circle.id == circles[5].id)
        assert assigned.joined and assigned.selected_by_user is False

        changed = await service.replace_settings(
            "administrator", CircleSettingsUpdate(maxMemberships=6), "synthetic-setting-change"
        )
        assert changed.max_memberships == 6
        await service.join("member", circles[0].id, "synthetic-sixth-membership")
        await service.update(
            "administrator", circles[0].id, CircleUpdate(active=False), "synthetic-deactivate"
        )
        inactive_joined = next(
            circle for circle in await service.list_mine("member") if circle.id == circles[0].id
        )
        assert inactive_joined.joined and not inactive_joined.active

        await service.remove("administrator", member, circles[5].id, "synthetic-administrator-removal")
        async with pool.acquire() as connection:
            active_count = await connection.fetchval(
                """SELECT count(*) FROM engagement_app.circle_memberships
                   WHERE user_id=$1 AND left_at IS NULL""",
                member,
            )
            actions = await connection.fetch(
                """SELECT action FROM engagement_app.audit_events
                   WHERE entity_type='circle' ORDER BY id"""
            )
        assert active_count == 5
        assert "circle.created" in {row["action"] for row in actions}
        assert "circle.membership.joined" in {row["action"] for row in actions}
        assert "circle.settings.replaced" in {row["action"] for row in actions}
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
