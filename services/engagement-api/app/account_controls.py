"""Week 2 audited account-control candidate; activation stays separate."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.authorization import Permission
from app.member_auth import MemberSessionFailure


class StatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def nonblank_reason(self):
        if len(self.reason.strip()) < 3:
            raise ValueError("An account change requires an explanation")
        return self


class RoleChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["member", "contributor", "administrator"]
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def nonblank_reason(self):
        if len(self.reason.strip()) < 3:
            raise ValueError("An account change requires an explanation")
        return self


class AccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: UUID
    role: Literal["member", "contributor", "administrator"]
    status: Literal["invited", "active", "suspended", "deleted"]
    display_name: str | None = Field(default=None, alias="displayName", min_length=1, max_length=120)
    preferred_language: Literal["en", "bn", "hi"] | None = Field(default=None, alias="preferredLanguage")
    profile_complete: bool = Field(alias="profileComplete")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


def conflict():
    return MemberSessionFailure(
        status=409, code="CONFLICT", title="Account change requires a different setup"
    )


class UnconfiguredAccountControls:
    async def status(self, token, target, request, trace):
        raise MemberSessionFailure(
            status=503, code="DEPENDENCY_UNAVAILABLE", title="Account service is temporarily unavailable"
        )

    async def role(self, token, target, request, trace):
        return await self.status(token, target, request, trace)


class PostgresAccountControls:
    def __init__(self, authorization):
        self._authorization = authorization

    async def _target(self, connection, target):
        row = await connection.fetchrow(
            """SELECT id,role::text,status::text,phone_e164,identity_provider_subject
               FROM engagement_app.app_users WHERE id=$1 FOR UPDATE""",
            target,
        )
        if row is None:
            raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Resource not found")
        if row["status"] not in {"active", "suspended"}:
            # Invitations are activated through credential enrollment, not
            # silently switched on by the suspend/reactivate operation.
            raise conflict()
        return row

    async def _protect_last_administrator(self, connection, row, removing):
        if row["role"] == "administrator" and row["status"] == "active" and removing:
            count = await connection.fetchval(
                """SELECT count(*) FROM engagement_app.app_users u
                   JOIN engagement_app.staff_credentials c ON c.user_id=u.id
                   WHERE u.role='administrator' AND u.status='active'
                     AND c.second_factor_enabled AND c.mfa_secret_ciphertext IS NOT NULL"""
            )
            if count < 2:
                raise conflict()

    async def _summary(self, connection, target):
        row = await connection.fetchrow(
            """SELECT u.id,u.role::text,u.status::text,u.created_at,u.updated_at,
                      p.display_name,p.preferred_language,
                      COALESCE(p.profile_complete,false) AS profile_complete
               FROM engagement_app.app_users u LEFT JOIN engagement_app.user_profiles p ON p.user_id=u.id
               WHERE u.id=$1""",
            target,
        )
        return AccountSummary(**dict(row))

    async def _audit(self, connection, actor, target, action, reason, trace, metadata):
        await connection.execute(
            """INSERT INTO engagement_app.audit_events
               (actor_user_id,action,entity_type,entity_id,reason,trace_id,metadata)
               VALUES($1,$2,'app_user',$3,$4,$5,$6::jsonb)""",
            actor,
            action,
            str(target),
            reason,
            trace,
            json.dumps(metadata),
        )

    async def status(self, token, target: UUID, request: StatusChangeRequest, trace_id):
        async with self._authorization.transaction(token, Permission.ACCOUNT_STATUS, target=target) as (
            connection,
            actor,
        ):
            row = await self._target(connection, target)
            await self._protect_last_administrator(connection, row, request.status == "suspended")
            await connection.execute(
                "UPDATE engagement_app.app_users SET status=$2,updated_at=now() WHERE id=$1",
                target,
                request.status,
            )
            if request.status == "suspended":
                await connection.execute(
                    """UPDATE engagement_app.auth_sessions SET revoked_at=now()
                       WHERE user_id=$1 AND revoked_at IS NULL""",
                    target,
                )
            await self._audit(
                connection,
                actor.user_id,
                target,
                "account.status",
                request.reason,
                trace_id,
                {"from": row["status"], "to": request.status},
            )
            return await self._summary(connection, target)

    async def role(self, token, target: UUID, request: RoleChangeRequest, trace_id):
        async with self._authorization.transaction(token, Permission.ACCOUNT_ROLE, target=target) as (
            connection,
            actor,
        ):
            row = await self._target(connection, target)
            await self._protect_last_administrator(connection, row, request.role != "administrator")
            status = row["status"]
            if request.role != row["role"]:
                if request.role == "member":
                    if not row["phone_e164"] or not row["identity_provider_subject"]:
                        raise conflict()
                    await connection.execute(
                        "DELETE FROM engagement_app.staff_credentials WHERE user_id=$1", target
                    )
                elif request.role == "administrator":
                    credential = await connection.fetchrow(
                        """SELECT second_factor_enabled,mfa_secret_ciphertext,last_accepted_totp_step
                           FROM engagement_app.staff_credentials WHERE user_id=$1 FOR UPDATE""",
                        target,
                    )
                    if (
                        not credential
                        or not credential["second_factor_enabled"]
                        or credential["mfa_secret_ciphertext"] is None
                        or credential["last_accepted_totp_step"] is None
                    ):
                        raise conflict()
                elif row["role"] == "member":
                    status = "invited"
                await connection.execute(
                    "UPDATE engagement_app.app_users SET role=$2,status=$3,updated_at=now() WHERE id=$1",
                    target,
                    request.role,
                    status,
                )
                # V0003 also provides a database-level revocation guard. Keep
                # explicit revocation here for clear service intent.
                await connection.execute(
                    """UPDATE engagement_app.auth_sessions SET revoked_at=now()
                       WHERE user_id=$1 AND revoked_at IS NULL""",
                    target,
                )
            await self._audit(
                connection,
                actor.user_id,
                target,
                "account.role",
                request.reason,
                trace_id,
                {"from": row["role"], "to": request.role},
            )
            return await self._summary(connection, target)
