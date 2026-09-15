"""PostgreSQL predefined circles, suggestions and membership controls."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg
from pydantic import ValidationError

from app.authorization import Permission
from app.circles import (
    CircleCreate,
    CircleSettings,
    CircleSettingsUpdate,
    CircleSuggestionRules,
    CircleSummary,
    CircleUpdate,
    is_suggested,
)
from app.member_auth import MemberSessionFailure


def unavailable() -> MemberSessionFailure:
    return MemberSessionFailure(
        status=503, code="DEPENDENCY_UNAVAILABLE", title="Circle service is temporarily unavailable"
    )


async def verify_circle_schema(pool) -> None:
    async with pool.acquire() as connection:
        tables = await connection.fetchval(
            """SELECT count(*) FROM information_schema.tables
               WHERE table_schema='engagement_app'
                 AND table_name IN ('circles','circle_memberships','circle_configuration')"""
        )
    if tables != 3:
        raise RuntimeError("Circle database migration has not been applied")


class UnconfiguredCircleService:
    async def list_mine(self, token):
        raise unavailable()

    async def list_all(self, token):
        raise unavailable()

    async def create(self, token, request, trace_id):
        raise unavailable()

    async def update(self, token, circle_id, request, trace_id):
        raise unavailable()

    async def join(self, token, circle_id, trace_id):
        raise unavailable()

    async def leave(self, token, circle_id, trace_id):
        raise unavailable()

    async def assign(self, token, user_id, circle_id, trace_id):
        raise unavailable()

    async def remove(self, token, user_id, circle_id, trace_id):
        raise unavailable()

    async def settings(self, token):
        raise unavailable()

    async def replace_settings(self, token, request, trace_id):
        raise unavailable()


class PostgresCircleService:
    def __init__(self, authorization):
        self._authorization = authorization

    @staticmethod
    def _rules(value) -> CircleSuggestionRules:
        try:
            return CircleSuggestionRules.model_validate(
                json.loads(value) if isinstance(value, str) else value
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise unavailable() from exc

    @classmethod
    def _summary(cls, row, **values) -> CircleSummary:
        fields = dict(row)
        rules = cls._rules(fields.pop("suggestion_rules"))
        return CircleSummary(**fields, suggestionRules=rules, **values)

    async def _list(self, connection, user_id: UUID) -> list[CircleSummary]:
        profile = await connection.fetchrow(
            """SELECT preferred_language,interests FROM engagement_app.user_profiles
               WHERE user_id=$1""",
            user_id,
        )
        try:
            interests_value = profile["interests"] if profile else []
            interests = (
                json.loads(interests_value) if isinstance(interests_value, str) else list(interests_value)
            )
            if not isinstance(interests, list) or any(not isinstance(value, str) for value in interests):
                raise TypeError("Profile interests are malformed")
        except (json.JSONDecodeError, TypeError) as exc:
            raise unavailable() from exc
        language = profile["preferred_language"] if profile else None
        rows = await connection.fetch(
            """SELECT c.id,c.name,c.description,c.active,c.suggestion_rules,c.created_at,c.updated_at,
                      m.selected_by_user,(m.id IS NOT NULL) AS joined
               FROM engagement_app.circles c
               LEFT JOIN engagement_app.circle_memberships m
                 ON m.circle_id=c.id AND m.user_id=$1 AND m.left_at IS NULL
               WHERE c.active OR m.id IS NOT NULL
               ORDER BY c.name,c.id""",
            user_id,
        )
        result = []
        for row in rows:
            rules = self._rules(row["suggestion_rules"])
            result.append(self._summary(row, suggested=is_suggested(rules, interests, language)))
        return result

    async def list_mine(self, token) -> list[CircleSummary]:
        owner = self._authorization._proof(token)[0]
        async with self._authorization.transaction(token, Permission.VIEW_CIRCLES, target=owner) as (
            connection,
            _,
        ):
            return await self._list(connection, owner)

    async def list_all(self, token) -> list[CircleSummary]:
        async with self._authorization.transaction(token, Permission.MANAGE_CIRCLES) as (
            connection,
            _,
        ):
            rows = await connection.fetch(
                """SELECT id,name,description,active,suggestion_rules,created_at,updated_at
                   FROM engagement_app.circles ORDER BY name,id"""
            )
            return [self._summary(row, joined=False, selectedByUser=None, suggested=False) for row in rows]

    async def _circle(self, connection, circle_id, *, active_only=False):
        query = """SELECT id,name,description,active,suggestion_rules,created_at,updated_at
                   FROM engagement_app.circles WHERE id=$1"""
        if active_only:
            query += " AND active"
        row = await connection.fetchrow(query + " FOR UPDATE", circle_id)
        if row is None:
            raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Circle was not found")
        return row

    async def _audit(self, connection, actor, action, entity, trace, metadata):
        await connection.execute(
            """INSERT INTO engagement_app.audit_events
               (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
               VALUES($1,$2,'circle',$3,$4,$5::jsonb)""",
            actor,
            action,
            str(entity),
            trace,
            json.dumps(metadata),
        )

    async def create(self, token, request: CircleCreate, trace_id) -> CircleSummary:
        async with self._authorization.transaction(token, Permission.MANAGE_CIRCLES) as (
            connection,
            actor,
        ):
            try:
                row = await connection.fetchrow(
                    """INSERT INTO engagement_app.circles
                       (name,description,suggestion_rules,created_by)
                       VALUES($1,$2,$3::jsonb,$4)
                       RETURNING id,name,description,active,suggestion_rules,created_at,updated_at""",
                    request.name,
                    request.description,
                    request.suggestion_rules.model_dump_json(by_alias=True),
                    actor.user_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="A circle with this name already exists"
                ) from exc
            await self._audit(connection, actor.user_id, "circle.created", row["id"], trace_id, {})
            return self._summary(row, joined=False, selectedByUser=None, suggested=False)

    async def update(self, token, circle_id: UUID, request: CircleUpdate, trace_id) -> CircleSummary:
        async with self._authorization.transaction(token, Permission.MANAGE_CIRCLES) as (
            connection,
            actor,
        ):
            current = await self._circle(connection, circle_id)
            values = {
                "name": current["name"],
                "description": current["description"],
                "suggestion_rules": current["suggestion_rules"],
                "active": current["active"],
            }
            for field in request.model_fields_set:
                value = getattr(request, field)
                values[field] = value.model_dump_json(by_alias=True) if field == "suggestion_rules" else value
            try:
                row = await connection.fetchrow(
                    """UPDATE engagement_app.circles SET name=$2,description=$3,
                       suggestion_rules=$4::jsonb,active=$5,updated_at=now() WHERE id=$1
                       RETURNING id,name,description,active,suggestion_rules,created_at,updated_at""",
                    circle_id,
                    values["name"],
                    values["description"],
                    values["suggestion_rules"],
                    values["active"],
                )
            except asyncpg.UniqueViolationError as exc:
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="A circle with this name already exists"
                ) from exc
            await self._audit(
                connection,
                actor.user_id,
                "circle.updated",
                circle_id,
                trace_id,
                {"changedFields": sorted(request.model_fields_set)},
            )
            return self._summary(row, joined=False, selectedByUser=None, suggested=False)

    async def _membership(self, token, user_id, circle_id, trace_id, *, join, selected_by_user):
        permission = (
            Permission.OWN_CIRCLE_MEMBERSHIPS if selected_by_user else Permission.MANAGE_CIRCLE_MEMBERSHIPS
        )
        async with self._authorization.transaction(token, permission, target=user_id) as (
            connection,
            actor,
        ):
            user = await connection.fetchrow(
                """SELECT role::text,status::text FROM engagement_app.app_users
                   WHERE id=$1 FOR UPDATE""",
                user_id,
            )
            if user is None or user["role"] != "member" or user["status"] != "active":
                raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Member was not found")
            await self._circle(connection, circle_id, active_only=join)
            membership = await connection.fetchrow(
                """SELECT id FROM engagement_app.circle_memberships
                   WHERE user_id=$1 AND circle_id=$2 AND left_at IS NULL FOR UPDATE""",
                user_id,
                circle_id,
            )
            changed = False
            if join and membership is None:
                limit = await connection.fetchval(
                    "SELECT max_memberships FROM engagement_app.circle_configuration WHERE singleton"
                )
                count = await connection.fetchval(
                    """SELECT count(*) FROM engagement_app.circle_memberships
                       WHERE user_id=$1 AND left_at IS NULL""",
                    user_id,
                )
                if count >= limit:
                    raise MemberSessionFailure(
                        status=409, code="CIRCLE_LIMIT_REACHED", title="Circle membership limit reached"
                    )
                await connection.execute(
                    """INSERT INTO engagement_app.circle_memberships
                       (circle_id,user_id,selected_by_user) VALUES($1,$2,$3)""",
                    circle_id,
                    user_id,
                    selected_by_user,
                )
                changed = True
            elif not join and membership is not None:
                await connection.execute(
                    "UPDATE engagement_app.circle_memberships SET left_at=now() WHERE id=$1",
                    membership["id"],
                )
                changed = True
            if changed:
                await self._audit(
                    connection,
                    actor.user_id,
                    "circle.membership.joined" if join else "circle.membership.left",
                    circle_id,
                    trace_id,
                    {"memberId": str(user_id), "selectedByUser": selected_by_user},
                )

    async def join(self, token, circle_id, trace_id):
        owner = self._authorization._proof(token)[0]
        await self._membership(token, owner, circle_id, trace_id, join=True, selected_by_user=True)

    async def leave(self, token, circle_id, trace_id):
        owner = self._authorization._proof(token)[0]
        await self._membership(token, owner, circle_id, trace_id, join=False, selected_by_user=True)

    async def assign(self, token, user_id, circle_id, trace_id):
        await self._membership(token, user_id, circle_id, trace_id, join=True, selected_by_user=False)

    async def remove(self, token, user_id, circle_id, trace_id):
        await self._membership(token, user_id, circle_id, trace_id, join=False, selected_by_user=False)

    async def settings(self, token) -> CircleSettings:
        async with self._authorization.transaction(token, Permission.MANAGE_CIRCLES) as (
            connection,
            _,
        ):
            row = await connection.fetchrow(
                """SELECT max_memberships,updated_at FROM engagement_app.circle_configuration
                   WHERE singleton"""
            )
            if row is None:
                raise unavailable()
            return CircleSettings(**dict(row))

    async def replace_settings(self, token, request: CircleSettingsUpdate, trace_id) -> CircleSettings:
        async with self._authorization.transaction(token, Permission.MANAGE_CIRCLES) as (
            connection,
            actor,
        ):
            row = await connection.fetchrow(
                """UPDATE engagement_app.circle_configuration
                   SET max_memberships=$1,updated_by=$2,updated_at=now() WHERE singleton
                   RETURNING max_memberships,updated_at""",
                request.max_memberships,
                actor.user_id,
            )
            if row is None:
                raise unavailable()
            await self._audit(
                connection,
                actor.user_id,
                "circle.settings.replaced",
                actor.user_id,
                trace_id,
                {"maxMemberships": request.max_memberships},
            )
            return CircleSettings(**dict(row))
