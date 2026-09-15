"""Notification preferences against GitHub's disposable PostgreSQL 16 only."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

from app.authorization import Permission, Principal
from app.notification_preferences import NotificationPreferencesUpdate
from app.postgres_notification_preferences import PostgresNotificationPreferencesService

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASELINE = Path(__file__).parents[3] / "database" / "migrations" / "V0001__engagement_baseline.sql"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL 16")


class DirectAuthorization:
    def __init__(self, pool, owner):
        self.pool = pool
        self.owner = owner

    def _proof(self, proof_value):
        return self.owner, uuid4(), "member", None

    @asynccontextmanager
    async def transaction(self, proof_value, permission, *, target):
        assert permission == Permission.OWN_NOTIFICATIONS and target == self.owner
        async with self.pool.acquire() as connection, connection.transaction():
            yield connection, Principal(self.owner, uuid4(), "member")


@pytest.mark.anyio
async def test_real_postgres_preference_defaults_replacement_and_audit():
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

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            owner = await connection.fetchval(
                """INSERT INTO engagement_app.app_users
                   (public_id,role,status,identity_provider_subject)
                   VALUES($1,'member','active',$2) RETURNING id""",
                f"AMI-SYN-{uuid4().hex[:16]}",
                f"synthetic-notifications-{uuid4()}",
            )
        service = PostgresNotificationPreferencesService(DirectAuthorization(pool, owner))
        initial = await service.get("synthetic-proof")
        assert initial.event_reminders and initial.content_updates
        assert not initial.delivery_window.enabled

        saved = await service.replace(
            "synthetic-proof",
            NotificationPreferencesUpdate(
                eventReminders=True,
                contentUpdates=False,
                deliveryWindow={
                    "enabled": True,
                    "timeZone": "Asia/Kolkata",
                    "startLocalTime": "22:00",
                    "endLocalTime": "06:00",
                },
            ),
            "synthetic-notification-trace",
        )
        assert saved.event_reminders and not saved.content_updates
        assert saved.delivery_window.start_local_time == "22:00"
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT push_events,push_content,time_zone
                   FROM engagement_app.notification_preferences WHERE user_id=$1""",
                owner,
            )
            assert tuple(row) == (True, False, "Asia/Kolkata")
            audit = await connection.fetchrow(
                """SELECT action,trace_id,metadata FROM engagement_app.audit_events
                   WHERE actor_user_id=$1""",
                owner,
            )
            assert audit["action"] == "notification.preferences.replaced"
            assert audit["trace_id"] == "synthetic-notification-trace"
            assert json.loads(audit["metadata"]) == {"windowEnabled": True}
    finally:
        await pool.close()
        cleanup = await asyncpg.connect(DATABASE_URL)
        try:
            await cleanup.execute("DROP SCHEMA IF EXISTS engagement_app CASCADE")
        finally:
            await cleanup.close()
