"""Administrator review of private Contributor content."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure

RejectionReason = Literal[
    "copyright_permission",
    "unsafe_inappropriate",
    "misleading",
    "poor_quality",
    "duplicate",
    "other",
]

REASON_LABELS = {
    "approved": "Approved",
    "copyright_permission": "Copyright or permission concern",
    "unsafe_inappropriate": "Unsafe or inappropriate content",
    "misleading": "Misleading content",
    "poor_quality": "Poor quality",
    "duplicate": "Duplicate content",
    "other": "Other",
}


def unavailable():
    return MemberSessionFailure(
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        title="Content moderation service is temporarily unavailable",
    )


class ModerationQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    contributor_id: UUID = Field(alias="contributorId")
    contributor_display_name: str | None = Field(alias="contributorDisplayName")
    kind: Literal["video", "audio", "pdf"]
    title: str
    description: str | None
    language: Literal["en", "bn", "hi"]
    content_type: str = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    scan_status: Literal["pending", "clean", "rejected", "failed"] = Field(alias="scanStatus")
    rights_confirmed_at: datetime = Field(alias="rightsConfirmedAt")
    submitted_at: datetime = Field(alias="submittedAt")


class ModerationPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    preview_url: AnyUrl = Field(alias="previewUrl")
    expires_at: datetime = Field(alias="expiresAt")


class ModerationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    outcome: Literal["approved", "rejected"]
    reason_code: Literal[
        "approved",
        "copyright_permission",
        "unsafe_inappropriate",
        "misleading",
        "poor_quality",
        "duplicate",
        "other",
    ] = Field(alias="reasonCode")
    note: str | None = Field(default=None, max_length=900)

    @model_validator(mode="after")
    def validate_reason(self):
        self.note = self.note.strip() or None if self.note is not None else None
        if self.outcome == "approved" and self.reason_code != "approved":
            raise ValueError("Approval must use the approved reason code")
        if self.outcome == "rejected" and self.reason_code == "approved":
            raise ValueError("Rejection must use a rejection reason code")
        if self.reason_code == "other" and not self.note:
            raise ValueError("A note is required for the other reason")
        return self


class ModerationDecisionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_item_id: UUID = Field(alias="contentItemId")
    status: Literal["approved", "rejected"]
    reason_code: str = Field(alias="reasonCode")
    note: str | None
    decided_at: datetime = Field(alias="decidedAt")
    published: Literal[False] = False


class UnconfiguredContentModerationService:
    async def queue(self, token):
        raise unavailable()

    async def preview(self, token, content_item_id):
        raise unavailable()

    async def decide(self, token, content_item_id, request, trace_id):
        raise unavailable()


async def verify_content_moderation_schema(pool):
    from app.config import ConfigurationError

    async with pool.acquire() as connection:
        columns = await connection.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='engagement_app' AND table_name='moderation_decisions'
                 AND column_name IN ('reason_code','note')"""
        )
    if {row["column_name"] for row in columns} != {"reason_code", "note"}:
        raise ConfigurationError("The content-moderation database migration is required")


class GoogleModerationPreviewStorage:
    def __init__(self, signed_storage):
        self._storage = signed_storage

    async def preview_url(self, object_key: str, expires_seconds: int):
        safe_key = (
            r"content-quarantine/[0-9a-f-]{36}/[0-9a-f-]{36}/"
            r"[0-9a-f-]{36}\.(mp4|mp3|m4a|pdf)"
        )
        if not re.fullmatch(safe_key, object_key):
            raise unavailable()
        return await self._storage._signed_url(
            "GET", self._storage.uploads_bucket, object_key, expires_seconds
        )


class PostgresContentModerationService:
    def __init__(self, authorization, storage, *, preview_seconds=120, now=lambda: datetime.now(UTC)):
        self.authorization = authorization
        self.storage = storage
        self.preview_seconds = preview_seconds
        self.now = now

    @staticmethod
    def _item(row) -> ModerationQueueItem:
        return ModerationQueueItem(
            contentItemId=row["id"],
            contributorId=row["contributor_id"],
            contributorDisplayName=row["display_name"],
            kind=row["kind"],
            title=row["title"],
            description=row["description"],
            language=row["language"],
            contentType=row["declared_media_type"],
            sizeBytes=row["size_bytes"],
            scanStatus=row["scan_status"],
            rightsConfirmedAt=row["rights_confirmed_at"],
            submittedAt=row["created_at"],
        )

    async def queue(self, token):
        async with self.authorization.transaction(
            token, Permission.VIEW_CONTENT_MODERATION
        ) as (connection, _):
            rows = await connection.fetch(
                """SELECT item.id,item.contributor_id,item.kind::text,item.title,
                          item.description,item.language,item.rights_confirmed_at,item.created_at,
                          profile.display_name,asset.declared_media_type,asset.size_bytes,
                          asset.scan_status
                   FROM engagement_app.content_items AS item
                   LEFT JOIN engagement_app.user_profiles AS profile
                     ON profile.user_id=item.contributor_id
                   JOIN LATERAL (
                     SELECT declared_media_type,size_bytes,scan_status
                     FROM engagement_app.content_assets
                     WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   WHERE item.status='pending'
                   ORDER BY item.created_at,item.id
                   LIMIT 100"""
            )
        return [self._item(row) for row in rows]

    async def preview(self, token, content_item_id: UUID):
        async with self.authorization.transaction(
            token, Permission.VIEW_CONTENT_MODERATION
        ) as (connection, _):
            row = await connection.fetchrow(
                """SELECT asset.object_key
                   FROM engagement_app.content_items AS item
                   JOIN LATERAL (
                     SELECT object_key FROM engagement_app.content_assets
                     WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   WHERE item.id=$1 AND item.status='pending'""",
                content_item_id,
            )
        if row is None:
            raise MemberSessionFailure(
                status=404, code="NOT_FOUND", title="Pending content was not found"
            )
        expires_at = self.now().astimezone(UTC) + timedelta(seconds=self.preview_seconds)
        url = await self.storage.preview_url(row["object_key"], self.preview_seconds)
        return ModerationPreview(
            contentItemId=content_item_id, previewUrl=url, expiresAt=expires_at
        )

    async def decide(
        self,
        token,
        content_item_id: UUID,
        request: ModerationDecisionRequest,
        trace_id: str,
    ):
        decided_at = self.now().astimezone(UTC)
        async with self.authorization.transaction(
            token, Permission.DECIDE_CONTENT_MODERATION
        ) as (connection, principal):
            row = await connection.fetchrow(
                """SELECT item.status::text,item.contributor_id,asset.scan_status
                   FROM engagement_app.content_items AS item
                   JOIN LATERAL (
                     SELECT scan_status FROM engagement_app.content_assets
                     WHERE content_item_id=item.id
                     ORDER BY created_at DESC,id DESC LIMIT 1
                   ) AS asset ON true
                   WHERE item.id=$1 FOR UPDATE OF item""",
                content_item_id,
            )
            if row is None:
                raise MemberSessionFailure(
                    status=404, code="NOT_FOUND", title="Content was not found"
                )
            if row["status"] != "pending":
                raise MemberSessionFailure(
                    status=409, code="CONFLICT", title="Content already has a final decision"
                )
            if row["contributor_id"] == principal.user_id:
                raise MemberSessionFailure(
                    status=403,
                    code="FORBIDDEN",
                    title="Administrators cannot review their own submitted content",
                )
            if request.outcome == "approved" and row["scan_status"] in {"rejected", "failed"}:
                raise MemberSessionFailure(
                    status=409,
                    code="CONFLICT",
                    title="Content with a failed safety check cannot be approved",
                )
            reason = REASON_LABELS[request.reason_code]
            if request.note:
                reason = f"{reason}: {request.note}"
            await connection.execute(
                """INSERT INTO engagement_app.moderation_decisions
                   (id,content_item_id,administrator_id,outcome,reason,reason_code,note,decided_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                uuid4(),
                content_item_id,
                principal.user_id,
                request.outcome,
                reason,
                request.reason_code,
                request.note,
                decided_at,
            )
            await connection.execute(
                """UPDATE engagement_app.content_items
                   SET status=$2,updated_at=$3 WHERE id=$1""",
                content_item_id,
                request.outcome,
                decided_at,
            )
            await connection.execute(
                """INSERT INTO engagement_app.audit_events
                   (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
                   VALUES($1,'content.moderation.decided','content_item',$2,$3,
                     jsonb_build_object('outcome',$4::text,'reasonCode',$5::text))""",
                principal.user_id,
                str(content_item_id),
                trace_id,
                request.outcome,
                request.reason_code,
            )
        return ModerationDecisionReceipt(
            contentItemId=content_item_id,
            status=request.outcome,
            reasonCode=request.reason_code,
            note=request.note,
            decidedAt=decided_at,
        )
