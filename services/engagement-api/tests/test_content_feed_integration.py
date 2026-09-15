"""Feed visibility against GitHub's disposable PostgreSQL 16 only."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

from app.authorization import Permission, Principal
from app.content_feed import ContentPublicationRequest, PostgresContentFeedService

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASELINE = Path(__file__).parents[3] / "database" / "migrations" / "V0001__engagement_baseline.sql"
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
        if permission == Permission.MANAGE_CONTENT_PUBLICATION:
            assert role == "administrator"
        elif permission == Permission.VIEW_CONTENT_FEED:
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
        await setup.execute(BASELINE.read_text(encoding="utf-8"))
    finally:
        await setup.close()


@pytest.mark.anyio
async def test_real_postgres_publication_and_circle_visibility():
    await prepare_database()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    try:
        async with pool.acquire() as connection:
            administrator = await connection.fetchval(
                """INSERT INTO engagement_app.app_users (public_id,role,status,username)
                   VALUES($1,'administrator','active',$2) RETURNING id""",
                f"AMI-ADM-{uuid4().hex[:16]}",
                f"synthetic-feed-admin-{uuid4().hex[:12]}",
            )
            contributor = await connection.fetchval(
                """INSERT INTO engagement_app.app_users (public_id,role,status,username)
                   VALUES($1,'contributor','active',$2) RETURNING id""",
                f"AMI-CON-{uuid4().hex[:16]}",
                f"synthetic-feed-contributor-{uuid4().hex[:12]}",
            )
            members = []
            for index in range(2):
                members.append(
                    await connection.fetchval(
                        """INSERT INTO engagement_app.app_users
                           (public_id,role,status,identity_provider_subject)
                           VALUES($1,'member','active',$2) RETURNING id""",
                        f"AMI-MEM-{uuid4().hex[:16]}",
                        f"synthetic-feed-member-{index}-{uuid4()}",
                    )
                )
            circle = await connection.fetchval(
                """INSERT INTO engagement_app.circles (name,created_by)
                   VALUES($1,$2) RETURNING id""",
                f"Synthetic feed circle {uuid4().hex[:8]}",
                administrator,
            )
            await connection.execute(
                """INSERT INTO engagement_app.circle_memberships
                   (circle_id,user_id) VALUES($1,$2)""",
                circle,
                members[0],
            )
            content = await connection.fetchval(
                """INSERT INTO engagement_app.content_items
                   (contributor_id,kind,title,language,status)
                   VALUES($1,'video','Synthetic database feed','bn','approved') RETURNING id""",
                contributor,
            )
            asset = await connection.fetchval(
                """INSERT INTO engagement_app.content_assets
                   (content_item_id,object_key,declared_media_type,size_bytes,sha256,
                    quarantined,scan_status)
                   VALUES($1,$2,'video/mp4',1234,$3,true,'clean') RETURNING id""",
                content,
                f"content-quarantine/{contributor}/{content}/{uuid4()}.mp4",
                "a" * 64,
            )
        storage = Mock(
            promote=AsyncMock(return_value=f"content/{content}/{asset}.mp4"),
            member_url=AsyncMock(return_value="https://storage.googleapis.com/private"),
        )
        service = PostgresContentFeedService(
            DirectAuthorization(
                pool,
                {
                    "administrator": (administrator, "administrator"),
                    "member-one": (members[0], "member"),
                    "member-two": (members[1], "member"),
                },
            ),
            storage,
        )
        await service.publish(
            "administrator",
            content,
            ContentPublicationRequest(audience="circles", circleIds=[circle]),
            "synthetic-publication",
        )
        in_circle = await service.feed("member-one", 20, None)
        out_of_circle = await service.feed("member-two", 20, None)
        assert [item.content_item_id for item in in_circle.items] == [content]
        assert out_of_circle.items == []
        assert (await service.media("member-one", content)).content_type == "video/mp4"

        async with pool.acquire() as connection:
            await connection.execute(
                "UPDATE engagement_app.circles SET active=false WHERE id=$1", circle
            )
        assert (await service.feed("member-one", 20, None)).items == []
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
