"""Week 2 permission policy and same-transaction current-session authorization.

Consumers must perform protected database work on the yielded connection.
There is no public endpoint or runtime activation in this module alone.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

import asyncpg

from app.member_auth import MemberSessionFailure
from app.session_controls import denied


class Permission(StrEnum):
    OWN_PROFILE = "own-profile"
    OWN_ACCOUNT = "own-account"
    CREATE_STAFF = "create-staff"
    ACCOUNT_STATUS = "account-status"
    ACCOUNT_ROLE = "account-role"


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    role: Literal["member", "contributor", "administrator"]


def require_permission(principal: Principal, permission: Permission, target: UUID | None = None):
    allowed = False
    if permission in {Permission.OWN_PROFILE, Permission.OWN_ACCOUNT}:
        allowed = target == principal.user_id
    elif permission in {Permission.CREATE_STAFF, Permission.ACCOUNT_STATUS, Permission.ACCOUNT_ROLE}:
        allowed = principal.role == "administrator"
    if principal.role not in {"member", "contributor", "administrator"} or not allowed:
        raise MemberSessionFailure(status=403, code="FORBIDDEN", title="Permission denied")


class SessionAuthorization:
    def __init__(self, pool, member_controls, staff_controls=None, *, now=lambda: datetime.now(UTC)):
        self._pool, self._member, self._staff, self._now = pool, member_controls, staff_controls, now

    def _proof(self, token):
        try:
            user_id, session_id = self._member._claims(token)
            return user_id, session_id, "member", None
        except MemberSessionFailure:
            if self._staff is None:
                raise denied() from None
            return self._staff._claims(token)

    @asynccontextmanager
    async def transaction(self, token, permission, *, target=None):
        user_id, session_id, role, version = self._proof(token)
        now = self._now()
        if now.utcoffset() is None:
            raise ValueError("Authorization clock must be timezone-aware")
        now = now.astimezone(UTC)
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                if role == "member":
                    user = await connection.fetchrow(
                        """SELECT role::text, status::text FROM engagement_app.app_users
                           WHERE id=$1 FOR UPDATE""",
                        user_id,
                    )
                    if not user or user["role"] != "member":
                        raise denied()
                    if user["status"] == "suspended":
                        raise MemberSessionFailure(
                            status=403, code="ACCOUNT_SUSPENDED", title="Account is suspended"
                        )
                    if user["status"] != "active":
                        raise denied()
                else:
                    # Reuse the canonical user-first/credential-second staff check.
                    user, current_version = await self._staff._account(connection, user_id)
                    if user["role"] != role or current_version != version:
                        raise denied()
                query = """SELECT id FROM engagement_app.auth_sessions
                           WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL
                             AND replaced_by_session_id IS NULL AND expires_at>$3"""
                args = [session_id, user_id, now]
                if role != "member":
                    query += " AND staff_credential_version=$4"
                    args.append(version)
                session = await connection.fetchrow(query + " FOR UPDATE", *args)
                if not session:
                    raise denied()
                principal = Principal(user_id, session_id, role)
                require_permission(principal, permission, target)
                # Locks stay held until the consumer's mutation/audit commits.
                yield connection, principal
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Account service is temporarily unavailable",
                retryable=False,
            ) from exc
