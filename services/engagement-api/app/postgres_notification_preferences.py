"""PostgreSQL notification preferences with own-account authorization."""

from __future__ import annotations

from datetime import time

from pydantic import ValidationError

from app.authorization import Permission
from app.member_auth import MemberSessionFailure
from app.notification_preferences import (
    NotificationPreferences,
    NotificationPreferencesUpdate,
    default_preferences,
)
from app.profiles import NotificationWindow


class UnconfiguredNotificationPreferencesService:
    async def get(self, token):
        raise MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Notification preferences are temporarily unavailable",
        )

    async def replace(self, token, request, trace_id):
        return await self.get(token)


class PostgresNotificationPreferencesService:
    def __init__(self, authorization):
        self._authorization = authorization

    async def _read(self, connection, owner):
        row = await connection.fetchrow(
            """SELECT u.updated_at AS account_updated_at, n.enabled, n.window_start,
                      n.window_end, n.time_zone, n.push_events, n.push_content,
                      n.updated_at
               FROM engagement_app.app_users u
               LEFT JOIN engagement_app.notification_preferences n ON n.user_id=u.id
               WHERE u.id=$1""",
            owner,
        )
        if row is None:
            raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Account was not found")
        if row["updated_at"] is None:
            return default_preferences(row["account_updated_at"])
        enabled = bool(row["enabled"])
        try:
            return NotificationPreferences(
                event_reminders=row["push_events"],
                content_updates=row["push_content"],
                delivery_window=NotificationWindow(
                    enabled=enabled,
                    time_zone=row["time_zone"],
                    start_local_time=row["window_start"].strftime("%H:%M") if enabled else None,
                    end_local_time=row["window_end"].strftime("%H:%M") if enabled else None,
                ),
                updated_at=row["updated_at"],
            )
        except (ValidationError, ValueError, TypeError, AttributeError) as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Notification preferences are temporarily unavailable",
            ) from exc

    async def get(self, token):
        owner = self._authorization._proof(token)[0]
        async with self._authorization.transaction(token, Permission.OWN_NOTIFICATIONS, target=owner) as (
            connection,
            _,
        ):
            return await self._read(connection, owner)

    async def replace(self, token, request: NotificationPreferencesUpdate, trace_id: str):
        owner = self._authorization._proof(token)[0]
        async with self._authorization.transaction(token, Permission.OWN_NOTIFICATIONS, target=owner) as (
            connection,
            _,
        ):
            window = request.delivery_window
            if not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=$1)", window.time_zone
            ):
                raise MemberSessionFailure(
                    status=400, code="VALIDATION_FAILED", title="Notification preferences are invalid"
                )
            await connection.execute(
                """INSERT INTO engagement_app.notification_preferences
                   (user_id,enabled,window_start,window_end,time_zone,push_events,push_content)
                   VALUES($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT(user_id) DO UPDATE SET enabled=EXCLUDED.enabled,
                   window_start=EXCLUDED.window_start,window_end=EXCLUDED.window_end,
                   time_zone=EXCLUDED.time_zone,push_events=EXCLUDED.push_events,
                   push_content=EXCLUDED.push_content,updated_at=now()""",
                owner,
                window.enabled,
                time.fromisoformat(window.start_local_time) if window.enabled else None,
                time.fromisoformat(window.end_local_time) if window.enabled else None,
                window.time_zone,
                request.event_reminders,
                request.content_updates,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'notification.preferences.replaced','notification_preferences',
                          $2,$3,jsonb_build_object('windowEnabled',$4::boolean))""",
                owner,
                str(owner),
                trace_id,
                window.enabled,
            )
            return await self._read(connection, owner)
