"""Own-profile candidate; changes and minimal audit commit atomically."""

from __future__ import annotations

import json
from datetime import time

from pydantic import ValidationError

from app.authorization import Permission
from app.member_auth import MemberSessionFailure
from app.profiles import BroadLocation, NotificationWindow, Profile, ProfileUpdate


def _invalid():
    return MemberSessionFailure(status=400, code="VALIDATION_FAILED", title="Profile fields are invalid")


class UnconfiguredProfileService:
    async def get(self, token):
        raise MemberSessionFailure(
            status=503, code="DEPENDENCY_UNAVAILABLE", title="Profile service is temporarily unavailable"
        )

    async def update(self, token, request, trace_id):
        return await self.get(token)


async def verify_profile_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        ready = await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM pg_constraint
               WHERE conrelid='engagement_app.user_profiles'::regclass AND convalidated
                 AND conname='user_profiles_preferred_language_check'
                 AND pg_get_constraintdef(oid) LIKE '%''en''%')"""
        )
    if ready is not True:
        raise ConfigurationError("The approved English profile-language migration is required")


class PostgresProfileService:
    def __init__(self, authorization, photo_storage=None):
        self._authorization = authorization
        self._photo_storage = photo_storage

    async def _read(self, connection, user_id):
        row = await connection.fetchrow(
            """SELECT u.id, u.role::text, u.status::text, p.display_name, p.preferred_language,
                      p.created_at, p.updated_at, p.age_group, p.interests, p.photo_object_key,
                      p.country_code, p.state_name, p.city_name,
                      n.enabled, n.window_start, n.window_end, n.time_zone
               FROM engagement_app.user_profiles p JOIN engagement_app.app_users u ON u.id=p.user_id
               LEFT JOIN engagement_app.notification_preferences n ON n.user_id=p.user_id
               WHERE p.user_id=$1""",
            user_id,
        )
        if row is None:
            raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Profile has not been created")
        location = None
        if row["country_code"] is not None or row["state_name"] is not None or row["city_name"] is not None:
            values = {
                key: value
                for key, value in {
                    "country_code": row["country_code"],
                    "state": row["state_name"],
                    "city": row["city_name"],
                }.items()
                if value is not None
            }
            location = BroadLocation(**values)
        enabled = bool(row["enabled"] and row["window_start"] is not None and row["window_end"] is not None)
        try:
            return Profile(
                id=row["id"],
                role=row["role"],
                status=row["status"],
                display_name=row["display_name"],
                preferred_language=row["preferred_language"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                age_group=row["age_group"],
                interests=json.loads(row["interests"])
                if isinstance(row["interests"], str)
                else row["interests"],
                broad_location=location,
                # The private key itself is never returned. A viewing address is
                # short-lived and created only when the photo feature is active.
                photo_url=await self._photo_storage.view_url(row.get("photo_object_key"))
                if self._photo_storage is not None and row.get("photo_object_key")
                else None,
                notification_window=NotificationWindow(
                    enabled=enabled,
                    time_zone=row["time_zone"] or "UTC",
                    start_local_time=row["window_start"].strftime("%H:%M") if enabled else None,
                    end_local_time=row["window_end"].strftime("%H:%M") if enabled else None,
                ),
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise MemberSessionFailure(
                status=503, code="DEPENDENCY_UNAVAILABLE", title="Profile service is temporarily unavailable"
            ) from exc

    async def get(self, token):
        owner = self._authorization._proof(token)[0]
        async with self._authorization.transaction(token, Permission.OWN_PROFILE, target=owner) as (
            connection,
            _,
        ):
            return await self._read(connection, owner)

    async def update(self, token, request: ProfileUpdate, trace_id: str):
        owner = self._authorization._proof(token)[0]
        async with self._authorization.transaction(token, Permission.OWN_PROFILE, target=owner) as (
            connection,
            _,
        ):
            existing = await connection.fetchrow(
                "SELECT * FROM engagement_app.user_profiles WHERE user_id=$1 FOR UPDATE", owner
            )
            supplied = request.model_fields_set
            if existing is None and not {"display_name", "preferred_language"}.issubset(supplied):
                raise _invalid()
            values = (
                dict(existing)
                if existing is not None
                else dict(
                    display_name=None,
                    preferred_language=None,
                    age_group=None,
                    interests="[]",
                    country_code=None,
                    state_name=None,
                    city_name=None,
                )
            )
            for name in supplied & {"display_name", "preferred_language", "age_group"}:
                values[name] = getattr(request, name)
            if "interests" in supplied:
                values["interests"] = json.dumps(request.interests)
            if "broad_location" in supplied:
                location = request.broad_location
                values.update(
                    country_code=location.country_code if location else None,
                    state_name=location.state if location else None,
                    city_name=location.city if location else None,
                )
            window = request.notification_window
            if window is not None and not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=$1)", window.time_zone
            ):
                raise _invalid()
            await connection.execute(
                """INSERT INTO engagement_app.user_profiles
                  (user_id,display_name,preferred_language,age_group,interests,country_code,state_name,city_name,
                   profile_complete) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,true)
                  ON CONFLICT(user_id) DO UPDATE SET display_name=EXCLUDED.display_name,
                    preferred_language=EXCLUDED.preferred_language,age_group=EXCLUDED.age_group,
                    interests=EXCLUDED.interests,country_code=EXCLUDED.country_code,state_name=EXCLUDED.state_name,
                    city_name=EXCLUDED.city_name,profile_complete=true,updated_at=now()""",
                owner,
                values["display_name"],
                values["preferred_language"],
                values["age_group"],
                values["interests"],
                values["country_code"],
                values["state_name"],
                values["city_name"],
            )
            if window is not None:
                await connection.execute(
                    """INSERT INTO engagement_app.notification_preferences
                       (user_id,enabled,window_start,window_end,time_zone) VALUES($1,$2,$3,$4,$5)
                       ON CONFLICT(user_id) DO UPDATE SET enabled=EXCLUDED.enabled,
                       window_start=EXCLUDED.window_start,window_end=EXCLUDED.window_end,
                       time_zone=EXCLUDED.time_zone,updated_at=now()""",
                    owner,
                    window.enabled,
                    time.fromisoformat(window.start_local_time) if window.enabled else None,
                    time.fromisoformat(window.end_local_time) if window.enabled else None,
                    window.time_zone,
                )
            # No names, location, interest values or credentials enter the audit.
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'profile.updated','user_profile',$2,$3,$4::jsonb)""",
                owner,
                str(owner),
                trace_id,
                json.dumps({"fields": sorted(supplied), "created": existing is None}),
            )
            return await self._read(connection, owner)
