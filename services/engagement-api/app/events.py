"""Administrator-created events and circle-filtered Member event listing."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    audience: Literal["all_members", "circles"]
    circle_ids: list[UUID] = Field(default_factory=list, alias="circleIds", max_length=20)
    reminder_minutes_before: list[StrictInt] = Field(
        default_factory=list, alias="reminderMinutesBefore", max_length=5
    )

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Event title is too short")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_time_zone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Event times must include a time zone")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("circle_ids")
    @classmethod
    def unique_circles(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Event circles must be unique")
        return value

    @field_validator("reminder_minutes_before")
    @classmethod
    def valid_reminders(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or not 5 <= item <= 10_080 for item in value):
            raise ValueError("Reminder timing must be between five minutes and seven days")
        if len(value) != len(set(value)):
            raise ValueError("Reminder timings must be unique")
        return sorted(value, reverse=True)

    @model_validator(mode="after")
    def valid_shape(self):
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("Event end must be after its start")
        if self.audience == "all_members" and self.circle_ids:
            raise ValueError("An all-Member event cannot also select circles")
        if self.audience == "circles" and not self.circle_ids:
            raise ValueError("A circle event must select at least one circle")
        return self


class EventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    title: str
    description: str | None
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(alias="endsAt")
    audience: Literal["all_members", "circles"]
    circle_ids: list[UUID] = Field(alias="circleIds")
    reminder_minutes_before: list[int] = Field(alias="reminderMinutesBefore")
    join_kind: Literal["information_only"] = Field(alias="joinKind")
    created_at: datetime = Field(alias="createdAt")


class EventPage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: list[EventSummary]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class UnconfiguredEventService:
    async def create(self, *_args, **_kwargs):
        raise MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Event service is temporarily unavailable",
        )

    async def list_visible(self, *_args, **_kwargs):
        raise MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Event service is temporarily unavailable",
        )


async def verify_event_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        ready = await connection.fetchval(
            """SELECT to_regclass('engagement_app.events') IS NOT NULL
                      AND to_regclass('engagement_app.event_audiences') IS NOT NULL
                      AND to_regclass('engagement_app.event_reminder_rules') IS NOT NULL"""
        )
    if ready is not True:
        raise ConfigurationError("The event-service database migration is required")


class PostgresEventService:
    def __init__(self, authorization, *, now=lambda: datetime.now(UTC)):
        self.authorization = authorization
        self.now = now

    @staticmethod
    def _summary(row) -> EventSummary:
        circles = list(row["circle_ids"] or [])
        return EventSummary(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            startsAt=row["starts_at"],
            endsAt=row["ends_at"],
            audience="all_members" if row["all_members"] else "circles",
            circleIds=circles,
            reminderMinutesBefore=list(row["reminder_minutes_before"] or []),
            joinKind="information_only",
            createdAt=row["created_at"],
        )

    @staticmethod
    def _encode_cursor(period: str, row) -> str:
        raw = json.dumps(
            [period, row["starts_at"].astimezone(UTC).isoformat(), str(row["id"])],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @staticmethod
    def _decode_cursor(period: str, cursor: str | None):
        if cursor is None:
            return None, None
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", cursor):
            raise MemberSessionFailure(
                status=400, code="INVALID_CURSOR", title="Event cursor is invalid"
            )
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            values = json.loads(raw)
            if len(values) != 3 or values[0] != period:
                raise ValueError
            starts_at = datetime.fromisoformat(values[1])
            if starts_at.utcoffset() is None:
                raise ValueError
            return starts_at.astimezone(UTC), UUID(values[2])
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            raise MemberSessionFailure(
                status=400, code="INVALID_CURSOR", title="Event cursor is invalid"
            ) from None

    async def create(self, token, request: EventCreate, trace_id: str) -> EventSummary:
        now = self.now().astimezone(UTC)
        if request.starts_at <= now:
            raise MemberSessionFailure(
                status=400,
                code="VALIDATION_FAILED",
                title="Event start must be in the future",
            )
        event_id = uuid4()
        async with self.authorization.transaction(token, Permission.MANAGE_EVENTS) as (
            connection,
            principal,
        ):
            if request.audience == "circles":
                circles = await connection.fetch(
                    "SELECT id FROM engagement_app.circles WHERE id=ANY($1::uuid[]) AND active=true",
                    request.circle_ids,
                )
                if {row["id"] for row in circles} != set(request.circle_ids):
                    raise MemberSessionFailure(
                        status=409,
                        code="CONFLICT",
                        title="One or more selected circles are not active",
                    )
            await connection.execute(
                """INSERT INTO engagement_app.events
                   (id,created_by,title,description,starts_at,ends_at,join_kind,
                    join_reference_encrypted,active,created_at,updated_at)
                   VALUES($1,$2,$3,$4,$5,$6,'information_only',NULL,true,$7,$7)""",
                event_id,
                principal.user_id,
                request.title,
                request.description,
                request.starts_at,
                request.ends_at,
                now,
            )
            if request.audience == "all_members":
                await connection.execute(
                    """INSERT INTO engagement_app.event_audiences
                       (event_id,audience,circle_id) VALUES($1,'all_members',NULL)""",
                    event_id,
                )
            else:
                for circle_id in request.circle_ids:
                    await connection.execute(
                        """INSERT INTO engagement_app.event_audiences
                           (event_id,audience,circle_id) VALUES($1,'circle',$2)""",
                        event_id,
                        circle_id,
                    )
            for minutes in request.reminder_minutes_before:
                await connection.execute(
                    """INSERT INTO engagement_app.event_reminder_rules
                       (event_id,minutes_before,created_at) VALUES($1,$2,$3)""",
                    event_id,
                    minutes,
                    now,
                )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'event.created','event',$2,$3,
                     jsonb_build_object('audience',$4::text,'circleCount',$5::integer,
                                        'reminderCount',$6::integer))""",
                principal.user_id,
                str(event_id),
                trace_id,
                request.audience,
                len(request.circle_ids),
                len(request.reminder_minutes_before),
            )
        return EventSummary(
            id=event_id,
            title=request.title,
            description=request.description,
            startsAt=request.starts_at,
            endsAt=request.ends_at,
            audience=request.audience,
            circleIds=request.circle_ids,
            reminderMinutesBefore=request.reminder_minutes_before,
            joinKind="information_only",
            createdAt=now,
        )

    async def list_visible(
        self,
        token,
        period: Literal["upcoming", "past"],
        limit: int,
        cursor: str | None,
    ) -> EventPage:
        owner = self.authorization._proof(token)[0]
        cursor_time, cursor_id = self._decode_cursor(period, cursor)
        now = self.now().astimezone(UTC)
        async with self.authorization.transaction(
            token, Permission.VIEW_EVENTS, target=owner
        ) as (connection, _):
            rows = await connection.fetch(
                """SELECT event.id,event.title,event.description,event.starts_at,event.ends_at,
                            event.created_at,
                            EXISTS(SELECT 1 FROM engagement_app.event_audiences all_audience
                                   WHERE all_audience.event_id=event.id
                                     AND all_audience.audience='all_members') AS all_members,
                            COALESCE((SELECT array_agg(audience.circle_id ORDER BY audience.circle_id)
                                      FROM engagement_app.event_audiences audience
                                      WHERE audience.event_id=event.id
                                        AND audience.audience='circle'),ARRAY[]::uuid[]) AS circle_ids,
                            COALESCE((SELECT array_agg(rule.minutes_before ORDER BY rule.minutes_before DESC)
                                      FROM engagement_app.event_reminder_rules rule
                                      WHERE rule.event_id=event.id),ARRAY[]::integer[])
                                      AS reminder_minutes_before
                     FROM engagement_app.events event
                     WHERE event.active=true
                       AND (($2::text='upcoming' AND event.starts_at >= $3)
                            OR ($2::text='past' AND event.starts_at < $3))
                       AND ($4::timestamptz IS NULL
                            OR ($2::text='upcoming' AND (event.starts_at,event.id) > ($4,$5::uuid))
                            OR ($2::text='past' AND (event.starts_at,event.id) < ($4,$5::uuid)))
                       AND (EXISTS(SELECT 1 FROM engagement_app.event_audiences all_audience
                                   WHERE all_audience.event_id=event.id
                                     AND all_audience.audience='all_members')
                            OR EXISTS(
                              SELECT 1 FROM engagement_app.event_audiences audience
                              JOIN engagement_app.circle_memberships membership
                                ON membership.circle_id=audience.circle_id
                               AND membership.user_id=$1 AND membership.active=true
                              JOIN engagement_app.circles circle
                                ON circle.id=audience.circle_id AND circle.active=true
                              WHERE audience.event_id=event.id AND audience.audience='circle'))
                     ORDER BY
                       CASE WHEN $2::text='upcoming' THEN event.starts_at END ASC,
                       CASE WHEN $2::text='past' THEN event.starts_at END DESC,
                       CASE WHEN $2::text='upcoming' THEN event.id END ASC,
                       CASE WHEN $2::text='past' THEN event.id END DESC
                     LIMIT $6""",
                owner,
                period,
                now,
                cursor_time,
                cursor_id,
                limit + 1,
            )
        page_rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(period, page_rows[-1]) if len(rows) > limit else None
        )
        return EventPage(
            items=[self._summary(row) for row in page_rows], nextCursor=next_cursor
        )
