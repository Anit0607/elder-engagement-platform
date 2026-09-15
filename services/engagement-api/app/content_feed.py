"""Administrator publication and circle-filtered Member content feed."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure


def unavailable():
    return MemberSessionFailure(
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        title="Content feed is temporarily unavailable",
    )


class ContentPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    audience: Literal["all_members", "circles"]
    circle_ids: list[UUID] = Field(default_factory=list, alias="circleIds", max_length=20)

    @model_validator(mode="after")
    def validate_audience(self):
        if len(set(self.circle_ids)) != len(self.circle_ids):
            raise ValueError("Circle identifiers must be unique")
        if self.audience == "all_members" and self.circle_ids:
            raise ValueError("All-Member publication cannot also select circles")
        if self.audience == "circles" and not self.circle_ids:
            raise ValueError("Circle publication requires at least one circle")
        return self


class ContentPublicationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    audience: Literal["all_members", "circles"]
    circle_ids: list[UUID] = Field(alias="circleIds")
    published_at: datetime = Field(alias="publishedAt")


class FeedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    kind: Literal["video", "audio", "pdf", "youtube", "broadcast_replay"]
    title: str
    description: str | None
    language: Literal["en", "bn", "hi"] | None
    contributor_display_name: str | None = Field(alias="contributorDisplayName")
    published_at: datetime = Field(alias="publishedAt")


class FeedPage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: list[FeedItem]
    next_cursor: str | None = Field(alias="nextCursor")


class FeedMedia(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    media_url: AnyUrl = Field(alias="mediaUrl")
    content_type: str = Field(alias="contentType")
    expires_at: datetime = Field(alias="expiresAt")


class UnconfiguredContentFeedService:
    async def publish(self, token, content_item_id, request, trace_id):
        raise unavailable()

    async def feed(self, token, limit, cursor):
        raise unavailable()

    async def media(self, token, content_item_id):
        raise unavailable()


async def verify_content_feed_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        tables = await connection.fetch(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='engagement_app'
                 AND table_name IN ('content_items','content_assets','content_audiences',
                                    'circle_memberships','circles')"""
        )
    expected = {
        "content_items",
        "content_assets",
        "content_audiences",
        "circle_memberships",
        "circles",
    }
    if {row["table_name"] for row in tables} != expected:
        raise ConfigurationError("The approved-content feed database foundation is required")


class GoogleContentFeedStorage:
    """Move approved media out of quarantine and sign short-lived Member reads."""

    def __init__(self, signed_storage):
        self._storage = signed_storage

    @staticmethod
    def destination_key(content_item_id: UUID, asset_id: UUID, source_key: str) -> str:
        match = re.fullmatch(
            r"content-quarantine/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.(mp4|mp3|m4a|pdf)",
            source_key,
        )
        if not match:
            raise unavailable()
        return f"content/{content_item_id}/{asset_id}.{match.group(1)}"

    async def promote(self, content_item_id: UUID, asset_id: UUID, row) -> str:
        destination = self.destination_key(content_item_id, asset_id, row["object_key"])
        await asyncio.to_thread(self._promote_sync, row, destination)
        return destination

    def _promote_sync(self, row, destination: str):
        token = self._storage._access_token()
        headers = {"Authorization": f"Bearer {token}"}
        source_bucket = quote(self._storage.uploads_bucket, safe="")
        destination_bucket = quote(self._storage.approved_bucket, safe="")
        source_key = quote(row["object_key"], safe="")
        destination_key = quote(destination, safe="")
        source_url = f"https://storage.googleapis.com/storage/v1/b/{source_bucket}/o/{source_key}"
        source = self._storage._request("GET", source_url, headers=headers)
        if source.status_code == 404:
            if self._approved_matches(headers, destination_bucket, destination_key, row):
                return
            raise MemberSessionFailure(
                status=404, code="NOT_FOUND", title="Approved source file was not found"
            )
        if source.status_code != 200:
            raise unavailable()
        try:
            metadata = source.json()
            generation = str(metadata["generation"])
            size = int(metadata["size"])
        except (KeyError, TypeError, ValueError):
            raise unavailable() from None
        if (
            not re.fullmatch(r"[1-9][0-9]*", generation)
            or size != row["size_bytes"]
            or metadata.get("contentType") != row["declared_media_type"]
        ):
            raise MemberSessionFailure(
                status=409,
                code="CONFLICT",
                title="Approved file no longer matches the reviewed file",
            )
        copy_url = (
            f"https://storage.googleapis.com/storage/v1/b/{source_bucket}/o/{source_key}"
            f"/copyTo/b/{destination_bucket}/o/{destination_key}"
        )
        copied = self._storage._request(
            "POST",
            copy_url,
            headers={**headers, "Content-Type": "application/json"},
            params={"ifGenerationMatch": "0", "ifSourceGenerationMatch": generation},
            json={
                "contentType": row["declared_media_type"],
                "metadata": {"ee-sha256": row["sha256"]},
            },
        )
        if copied.status_code == 412:
            if not self._approved_matches(headers, destination_bucket, destination_key, row):
                raise unavailable()
        elif copied.status_code != 200:
            raise unavailable()
        self._storage._request(
            "DELETE", source_url, headers=headers, params={"ifGenerationMatch": generation}
        )

    def _approved_matches(self, headers, bucket: str, key: str, row) -> bool:
        url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{key}"
        existing = self._storage._request("GET", url, headers=headers)
        try:
            current = existing.json()
            return (
                existing.status_code == 200
                and int(current.get("size", -1)) == row["size_bytes"]
                and current.get("contentType") == row["declared_media_type"]
                and current.get("metadata", {}).get("ee-sha256") == row["sha256"]
            )
        except (TypeError, ValueError):
            return False

    async def member_url(self, object_key: str, expires_seconds: int):
        if not re.fullmatch(
            r"content/[0-9a-f-]{36}/[0-9a-f-]{36}\.(mp4|mp3|m4a|pdf)", object_key
        ):
            raise unavailable()
        return await self._storage._signed_url(
            "GET", self._storage.approved_bucket, object_key, expires_seconds
        )


class PostgresContentFeedService:
    def __init__(self, authorization, storage, *, media_seconds=300, now=lambda: datetime.now(UTC)):
        self.authorization = authorization
        self.storage = storage
        self.media_seconds = media_seconds
        self.now = now

    @staticmethod
    def _encode_cursor(row) -> str:
        raw = json.dumps(
            [row["published_at"].astimezone(UTC).isoformat(), str(row["id"])],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @staticmethod
    def _decode_cursor(cursor: str | None):
        if cursor is None:
            return None, None
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", cursor):
            raise MemberSessionFailure(
                status=400, code="INVALID_CURSOR", title="Feed cursor is invalid"
            )
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            values = json.loads(raw)
            published_at = datetime.fromisoformat(values[0])
            if published_at.utcoffset() is None:
                raise ValueError
            published_at = published_at.astimezone(UTC)
            content_id = UUID(values[1])
            if len(values) != 2:
                raise ValueError
            return published_at, content_id
        except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError):
            raise MemberSessionFailure(
                status=400, code="INVALID_CURSOR", title="Feed cursor is invalid"
            ) from None

    @staticmethod
    def _item(row):
        return FeedItem(
            contentItemId=row["id"],
            kind=row["kind"],
            title=row["title"],
            description=row["description"],
            language=row["language"],
            contributorDisplayName=row["display_name"],
            publishedAt=row["published_at"],
        )

    async def publish(
        self,
        token,
        content_item_id: UUID,
        request: ContentPublicationRequest,
        trace_id: str,
    ):
        published_at = self.now().astimezone(UTC)
        async with self.authorization.transaction(
            token, Permission.MANAGE_CONTENT_PUBLICATION
        ) as (connection, principal):
            row = await connection.fetchrow(
                """SELECT item.status::text,item.published_at,
                          asset.id AS asset_id,asset.object_key,asset.declared_media_type,
                          asset.size_bytes,asset.sha256,asset.scan_status,asset.quarantined
                   FROM engagement_app.content_items AS item
                   JOIN LATERAL (
                     SELECT id,object_key,declared_media_type,size_bytes,sha256,
                            scan_status,quarantined
                     FROM engagement_app.content_assets
                     WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   WHERE item.id=$1 FOR UPDATE OF item""",
                content_item_id,
            )
            if row is None:
                raise MemberSessionFailure(
                    status=404, code="NOT_FOUND", title="Approved content was not found"
                )
            if row["status"] != "approved" or row["published_at"] is not None:
                raise MemberSessionFailure(
                    status=409,
                    code="CONFLICT",
                    title="Content is not approved and waiting for publication",
                )
            if row["scan_status"] != "clean" or row["quarantined"] is not True:
                raise MemberSessionFailure(
                    status=409,
                    code="CONFLICT",
                    title="Content has not passed the required file checks",
                )
            if request.audience == "circles":
                circles = await connection.fetch(
                    "SELECT id FROM engagement_app.circles WHERE id=ANY($1::uuid[]) AND active=true",
                    request.circle_ids,
                )
                if {item["id"] for item in circles} != set(request.circle_ids):
                    raise MemberSessionFailure(
                        status=409,
                        code="CONFLICT",
                        title="One or more selected circles are not active",
                    )
            destination = await self.storage.promote(
                content_item_id, row["asset_id"], row
            )
            if request.audience == "all_members":
                await connection.execute(
                    """INSERT INTO engagement_app.content_audiences
                       (content_item_id,audience,circle_id) VALUES($1,'all_members',NULL)""",
                    content_item_id,
                )
            else:
                for circle_id in request.circle_ids:
                    await connection.execute(
                        """INSERT INTO engagement_app.content_audiences
                           (content_item_id,audience,circle_id) VALUES($1,'circle',$2)""",
                        content_item_id,
                        circle_id,
                    )
            await connection.execute(
                """UPDATE engagement_app.content_assets
                   SET object_key=$2,quarantined=false WHERE id=$1""",
                row["asset_id"],
                destination,
            )
            await connection.execute(
                """UPDATE engagement_app.content_items
                   SET published_at=$2,updated_at=$2 WHERE id=$1""",
                content_item_id,
                published_at,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'content.published','content_item',$2,$3,
                     jsonb_build_object('audience',$4::text,'circleCount',$5::integer))""",
                principal.user_id,
                str(content_item_id),
                trace_id,
                request.audience,
                len(request.circle_ids),
            )
        return ContentPublicationReceipt(
            contentItemId=content_item_id,
            audience=request.audience,
            circleIds=request.circle_ids,
            publishedAt=published_at,
        )

    async def feed(self, token, limit: int, cursor: str | None):
        owner = self.authorization._proof(token)[0]
        before_time, before_id = self._decode_cursor(cursor)
        async with self.authorization.transaction(
            token, Permission.VIEW_CONTENT_FEED, target=owner
        ) as (connection, _):
            rows = await connection.fetch(
                """SELECT item.id,item.kind::text,item.title,item.description,item.language,
                          item.published_at,profile.display_name
                   FROM engagement_app.content_items AS item
                   JOIN LATERAL (
                     SELECT quarantined FROM engagement_app.content_assets
                     WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   LEFT JOIN engagement_app.user_profiles AS profile
                     ON profile.user_id=item.contributor_id
                   WHERE item.status='approved' AND item.published_at IS NOT NULL
                     AND asset.quarantined=false
                     AND ($2::timestamptz IS NULL OR (item.published_at,item.id)<($2,$3))
                     AND EXISTS (
                       SELECT 1 FROM engagement_app.content_audiences AS audience
                       WHERE audience.content_item_id=item.id AND (
                         audience.audience='all_members' OR (
                           audience.audience='circle' AND EXISTS (
                             SELECT 1 FROM engagement_app.circle_memberships AS membership
                             JOIN engagement_app.circles AS circle
                               ON circle.id=membership.circle_id AND circle.active=true
                             WHERE membership.circle_id=audience.circle_id
                               AND membership.user_id=$1 AND membership.left_at IS NULL
                           )
                         )
                       )
                     )
                   ORDER BY item.published_at DESC,item.id DESC LIMIT $4""",
                owner,
                before_time,
                before_id,
                limit + 1,
            )
        visible = rows[:limit]
        return FeedPage(
            items=[self._item(row) for row in visible],
            nextCursor=self._encode_cursor(visible[-1]) if len(rows) > limit else None,
        )

    async def media(self, token, content_item_id: UUID):
        owner = self.authorization._proof(token)[0]
        async with self.authorization.transaction(
            token, Permission.VIEW_CONTENT_FEED, target=owner
        ) as (connection, _):
            row = await connection.fetchrow(
                """SELECT asset.object_key,asset.declared_media_type
                   FROM engagement_app.content_items AS item
                   JOIN LATERAL (
                     SELECT object_key,declared_media_type,quarantined
                     FROM engagement_app.content_assets WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   WHERE item.id=$2 AND item.status='approved' AND item.published_at IS NOT NULL
                     AND asset.quarantined=false
                     AND EXISTS (
                       SELECT 1 FROM engagement_app.content_audiences AS audience
                       WHERE audience.content_item_id=item.id AND (
                         audience.audience='all_members' OR (
                           audience.audience='circle' AND EXISTS (
                             SELECT 1 FROM engagement_app.circle_memberships AS membership
                             JOIN engagement_app.circles AS circle
                               ON circle.id=membership.circle_id AND circle.active=true
                             WHERE membership.circle_id=audience.circle_id
                               AND membership.user_id=$1 AND membership.left_at IS NULL
                           )
                         )
                       )
                     )""",
                owner,
                content_item_id,
            )
        if row is None:
            raise MemberSessionFailure(
                status=404, code="NOT_FOUND", title="Feed item was not found"
            )
        expires_at = self.now().astimezone(UTC) + timedelta(seconds=self.media_seconds)
        url = await self.storage.member_url(row["object_key"], self.media_seconds)
        return FeedMedia(
            contentItemId=content_item_id,
            mediaUrl=url,
            contentType=row["declared_media_type"],
            expiresAt=expires_at,
        )
