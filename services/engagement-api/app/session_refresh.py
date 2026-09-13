from __future__ import annotations

import hmac
import re
from datetime import UTC, timedelta
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from app.member_auth import MemberSessionFailure, SessionResponse, UserSummary
from app.session_controls import PostgresSessionControls


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    refresh_token: str = Field(alias="refreshToken", min_length=32, max_length=512)


def invalid_refresh() -> MemberSessionFailure:
    return MemberSessionFailure(status=401, code="INVALID_REFRESH_TOKEN", title="Sign in again")


class PostgresSessionRefresh(PostgresSessionControls):
    """Single-use Member refresh; preserve the family's original absolute expiry."""

    async def refresh(self, token: str) -> SessionResponse:
        if not isinstance(token, str) or not re.fullmatch(r"amr1_[A-Za-z0-9_-]{64}", token):
            raise invalid_refresh()
        token_hash = hmac.digest(self._refresh_pepper, token.encode(), "sha256").hex()
        for attempt in range(self._retry_attempts):
            failure = None
            result = None
            now = self._now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("session clock must be timezone-aware")
            now = now.astimezone(UTC)
            try:
                async with self._pool.acquire() as connection, connection.transaction():
                    # Read owner without locking a session; all writers lock user first.
                    owner = await connection.fetchrow(
                        "SELECT user_id FROM engagement_app.auth_sessions WHERE refresh_token_hash=$1",
                        token_hash,
                    )
                    if not owner:
                        raise invalid_refresh()
                    user = await connection.fetchrow(
                        """SELECT u.id, u.role::text AS role, u.status::text AS status,
                                  u.created_at, u.updated_at, p.display_name, p.preferred_language,
                                  COALESCE(p.profile_complete, false) AS profile_complete
                             FROM engagement_app.app_users AS u
                             LEFT JOIN engagement_app.user_profiles AS p ON p.user_id=u.id
                             WHERE u.id=$1 FOR UPDATE OF u""", owner["user_id"],
                    )
                    if not user or user["role"] != "member" or user["status"] not in {"active", "suspended"}:
                        raise invalid_refresh()
                    if user["status"] == "suspended":
                        raise MemberSessionFailure(
                            status=403, code="ACCOUNT_SUSPENDED", title="Account is suspended",
                        )
                    session = await connection.fetchrow(
                        """SELECT id, token_family_id, installation_id, platform, device_name,
                                  expires_at, revoked_at, replaced_by_session_id
                             FROM engagement_app.auth_sessions
                             WHERE refresh_token_hash=$1 AND user_id=$2 FOR UPDATE""",
                        token_hash, user["id"],
                    )
                    if not session:
                        raise invalid_refresh()
                    if session["revoked_at"] is not None:
                        raise MemberSessionFailure(status=401, code="SESSION_REVOKED", title="Sign in again")
                    if session["replaced_by_session_id"] is not None:
                        await connection.execute(
                            """UPDATE engagement_app.auth_sessions SET revoked_at=$3
                               WHERE user_id=$1 AND token_family_id=$2 AND revoked_at IS NULL""",
                            user["id"], session["token_family_id"], now,
                        )
                        # Raise only AFTER transaction commits: replay revocation must survive.
                        failure = MemberSessionFailure(
                            status=409, code="REFRESH_TOKEN_REUSED", title="Sign in again",
                        )
                    else:
                        expires_at = min(now + self._access_delta, session["expires_at"])
                        if expires_at - now < timedelta(seconds=60):
                            raise invalid_refresh()
                        session_id = uuid4()
                        tokens, new_hash = self._tokens(user["id"], session_id, now, expires_at)
                        await connection.execute(
                            """INSERT INTO engagement_app.auth_sessions (
                                id, user_id, token_family_id, refresh_token_hash, installation_id,
                                platform, device_name, created_at, last_seen_at, expires_at
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8,$9)""",
                            session_id, user["id"], session["token_family_id"], new_hash,
                            session["installation_id"], session["platform"], session["device_name"],
                            now, session["expires_at"],
                        )
                        await connection.execute(
                            """UPDATE engagement_app.auth_sessions
                               SET replaced_by_session_id=$2, last_seen_at=$3 WHERE id=$1""",
                            session["id"], session_id, now,
                        )
                        result = SessionResponse(
                            accessToken=tokens.access_token, refreshToken=tokens.refresh_token,
                            expiresInSeconds=tokens.expires_in_seconds,
                            user=UserSummary(
                                id=user["id"], role="member", status="active",
                                displayName=user["display_name"],
                                preferredLanguage=user["preferred_language"],
                                profileComplete=user["profile_complete"], createdAt=user["created_at"],
                                updatedAt=user["updated_at"],
                            ),
                        )
            except asyncpg.UniqueViolationError:
                if attempt + 1 < self._retry_attempts:
                    continue
                raise MemberSessionFailure(
                    status=503, code="DEPENDENCY_UNAVAILABLE",
                    title="Session service is temporarily unavailable",
                ) from None
            except (asyncpg.PostgresError, OSError, TimeoutError):
                raise MemberSessionFailure(
                    status=503, code="DEPENDENCY_UNAVAILABLE",
                    title="Session service is temporarily unavailable",
                ) from None
            if failure is not None:
                raise failure
            return result
        raise invalid_refresh()
