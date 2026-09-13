from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import asyncpg
import jwt
from pydantic import BaseModel, ConfigDict, Field

from app.member_auth import MemberSessionFailure, SessionResponse
from app.postgres_session_issuer import PostgresSessionIssuer


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    installation_id: UUID = Field(alias="installationId")
    platform: Literal["android", "ios", "web"]
    device_name: str | None = Field(default=None, alias="deviceName")
    current: bool
    created_at: datetime = Field(alias="createdAt")
    last_seen_at: datetime = Field(alias="lastSeenAt")


class SessionControls(Protocol):
    async def refresh(self, token: str) -> SessionResponse: ...
    async def list_sessions(self, token: str) -> list[SessionSummary]: ...
    async def logout(self, token: str) -> None: ...
    async def revoke(self, token: str, target: UUID) -> None: ...


def denied() -> MemberSessionFailure:
    return MemberSessionFailure(status=401, code="AUTHENTICATION_FAILED", title="Authentication failed")


class UnconfiguredSessionControls:
    async def refresh(self, token: str) -> SessionResponse:
        # Refresh credentials are single-use; do not advertise automatic replay.
        raise MemberSessionFailure(
            status=503, code="DEPENDENCY_UNAVAILABLE",
            title="Session service is temporarily unavailable",
        )

    async def _unavailable(self):
        raise MemberSessionFailure(
            status=503, code="DEPENDENCY_UNAVAILABLE",
            title="Session service is temporarily unavailable", retryable=True,
        )

    async def list_sessions(self, token: str) -> list[SessionSummary]:
        return await self._unavailable()

    async def logout(self, token: str) -> None:
        await self._unavailable()

    async def revoke(self, token: str, target: UUID) -> None:
        await self._unavailable()


class PostgresSessionControls(PostgresSessionIssuer):
    """Member-only session controls; database state is checked on every operation."""

    def _claims(self, token: str) -> tuple[UUID, UUID]:
        if not isinstance(token, str) or not 20 <= len(token) <= 8192:
            raise denied()
        try:
            claims = jwt.decode(
                token, self._signing_key, algorithms=["HS256"],
                issuer=self._issuer, audience=self._audience,
                options={"require": ["iss", "aud", "sub", "sid", "jti", "role", "iat", "nbf", "exp"],
                         "strict_aud": True},
            )
            if (
                claims["role"] != "member"
                or any(type(claims[key]) is not int for key in ("iat", "nbf", "exp"))
                or not 0 < claims["exp"] - claims["iat"] <= self._access_delta.total_seconds()
                or claims["nbf"] != claims["iat"]
            ):
                raise ValueError
            for key in ("sub", "sid", "jti"):
                if not isinstance(claims[key], str) or str(UUID(claims[key])) != claims[key]:
                    raise ValueError
            return UUID(claims["sub"]), UUID(claims["sid"])
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
            raise denied() from exc

    async def _operate(self, token: str, action: str, target: UUID | None = None):
        user_id, session_id = self._claims(token)
        now = self._now()
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                # User first, then sessions: serializes same-user removal and future refresh.
                user = await connection.fetchrow(
                    "SELECT role::text, status::text FROM engagement_app.app_users WHERE id=$1 FOR UPDATE",
                    user_id,
                )
                if not user or user["role"] != "member" or user["status"] == "deleted":
                    raise denied()
                if user["status"] == "suspended":
                    raise MemberSessionFailure(
                        status=403, code="ACCOUNT_SUSPENDED", title="Account is suspended",
                    )
                if user["status"] != "active":
                    raise denied()
                session = await connection.fetchrow(
                    """SELECT id FROM engagement_app.auth_sessions
                         WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL
                           AND replaced_by_session_id IS NULL AND expires_at > $3 FOR UPDATE""",
                    session_id, user_id, now,
                )
                if not session:
                    raise denied()
                await connection.execute(
                    "UPDATE engagement_app.auth_sessions SET last_seen_at=$2 WHERE id=$1",
                    session_id, now,
                )
                if action == "list":
                    rows = await connection.fetch(
                        """SELECT id, installation_id, platform, device_name, created_at, last_seen_at
                             FROM engagement_app.auth_sessions WHERE user_id=$1
                              AND revoked_at IS NULL AND replaced_by_session_id IS NULL AND expires_at > $2
                             ORDER BY created_at DESC, id""", user_id, now,
                    )
                    return [SessionSummary(
                        id=row["id"], installation_id=row["installation_id"], platform=row["platform"],
                        device_name=row["device_name"], current=row["id"] == session_id,
                        created_at=row["created_at"], last_seen_at=row["last_seen_at"],
                    ) for row in rows]
                target_id = session_id if action == "logout" else target
                # An unavailable target and another user's target are indistinguishable.
                target_row = await connection.fetchrow(
                    """SELECT token_family_id FROM engagement_app.auth_sessions
                         WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL
                          AND replaced_by_session_id IS NULL AND expires_at > $3 FOR UPDATE""",
                    target_id, user_id, now,
                )
                if not target_row:
                    raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Resource not found")
                await connection.execute(
                    """UPDATE engagement_app.auth_sessions SET revoked_at=$3
                         WHERE user_id=$1 AND token_family_id=$2 AND revoked_at IS NULL""",
                    user_id, target_row["token_family_id"], now,
                )
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            raise MemberSessionFailure(
                status=503, code="DEPENDENCY_UNAVAILABLE",
                title="Session service is temporarily unavailable", retryable=True,
            ) from exc

    async def list_sessions(self, token: str) -> list[SessionSummary]:
        return await self._operate(token, "list")

    async def logout(self, token: str) -> None:
        await self._operate(token, "logout")

    async def revoke(self, token: str, target: UUID) -> None:
        await self._operate(token, "revoke", target)
