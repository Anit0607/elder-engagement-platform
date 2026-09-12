from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import jwt

from app.member_auth import (
    AuthenticationDependencyUnavailable,
    IssuedSession,
    MemberRecord,
    MemberSessionFailure,
)


@asynccontextmanager
async def _no_transaction():
    yield


class PostgresSessionIssuer:
    """Issue a signed access token and persist only a hash of the refresh token."""

    def __init__(
        self,
        pool: Any,
        *,
        signing_key: bytes,
        refresh_pepper: bytes,
        issuer: str,
        audience: str = "amiko-api",
        access_token_minutes: int = 10,
        refresh_token_days: int = 30,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        retry_attempts: int = 3,
        member_session_limit: int = 0,
    ) -> None:
        parsed_issuer = urlsplit(issuer)
        if (
            parsed_issuer.scheme != "https"
            or not parsed_issuer.hostname
            or parsed_issuer.path not in {"", "/"}
            or parsed_issuer.query
            or parsed_issuer.fragment
            or parsed_issuer.username
            or parsed_issuer.password
        ):
            raise ValueError("session issuer must be an HTTPS origin")
        if (
            not isinstance(signing_key, bytes)
            or not isinstance(refresh_pepper, bytes)
            or len(signing_key) < 32
            or len(refresh_pepper) < 32
        ):
            raise ValueError("session secrets must contain at least 32 bytes")
        if hmac.compare_digest(signing_key, refresh_pepper):
            raise ValueError("session signing and refresh secrets must be different")
        if not audience or len(audience) > 100:
            raise ValueError("session audience is invalid")
        if not 5 <= access_token_minutes <= 30:
            raise ValueError("access-token duration must be between 5 and 30 minutes")
        if not 1 <= refresh_token_days <= 90:
            raise ValueError("refresh-token duration must be between 1 and 90 days")
        if not 1 <= retry_attempts <= 5:
            raise ValueError("retry attempts must be between one and five")
        self._pool = pool
        self._signing_key = signing_key
        self._refresh_pepper = refresh_pepper
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._access_delta = timedelta(minutes=access_token_minutes)
        self._refresh_delta = timedelta(days=refresh_token_days)
        self._now = now
        self._retry_attempts = retry_attempts
        if not 0 <= member_session_limit <= 20:
            raise ValueError("Member session limit must be between zero and twenty")
        self._member_session_limit = member_session_limit

    async def _check_limit(self, connection, member: MemberRecord, issued_at: datetime):
        if not self._member_session_limit:
            return
        row = await connection.fetchrow(
            "SELECT role::text, status::text FROM engagement_app.app_users WHERE id=$1 FOR UPDATE", member.id,
        )
        if not row or row["role"] != "member" or row["status"] != "active":
            raise MemberSessionFailure(
                status=401, code="AUTHENTICATION_FAILED", title="Authentication failed",
            )
        recent = await connection.fetchval(
            "SELECT count(*) FROM engagement_app.auth_sessions WHERE user_id=$1 AND created_at >= $2",
            member.id, issued_at - timedelta(minutes=10),
        )
        if recent >= self._member_session_limit:
            raise MemberSessionFailure(
                status=429, code="RATE_LIMITED", title="Too many sign-in attempts; wait before trying again",
                retryable=True,
            )

    async def issue(
        self,
        member: MemberRecord,
        installation_id: UUID,
        platform: Literal["android", "ios"],
        device_name: str | None,
    ) -> IssuedSession:
        if member.role != "member" or member.status != "active":
            raise ValueError("only an active Member can receive a Member session")
        for attempt in range(self._retry_attempts):
            issued_at = self._now()
            if issued_at.tzinfo is None or issued_at.utcoffset() is None:
                raise ValueError("session clock must be timezone-aware")
            issued_at = issued_at.astimezone(UTC)
            session_id = uuid4()
            token_family_id = uuid4()
            access_expires_at = issued_at + self._access_delta
            refresh_expires_at = issued_at + self._refresh_delta
            refresh_token = f"amr1_{secrets.token_urlsafe(48)}"
            refresh_hash = hmac.digest(
                self._refresh_pepper, refresh_token.encode(), "sha256"
            ).hex()
            access_token = jwt.encode(
                {
                    "iss": self._issuer,
                    "aud": self._audience,
                    "sub": str(member.id),
                    "sid": str(session_id),
                    "jti": str(uuid4()),
                    "role": "member",
                    "iat": int(issued_at.timestamp()),
                    "nbf": int(issued_at.timestamp()),
                    "exp": int(access_expires_at.timestamp()),
                },
                self._signing_key,
                algorithm="HS256",
                headers={"typ": "JWT"},
            )
            try:
                async with self._pool.acquire() as connection:
                    transaction = (
                        connection.transaction() if self._member_session_limit else _no_transaction()
                    )
                    async with transaction:
                        await self._check_limit(connection, member, issued_at)
                        await connection.execute(
                        """
                        INSERT INTO engagement_app.auth_sessions (
                          id, user_id, token_family_id, refresh_token_hash,
                          installation_id, platform, device_name, created_at,
                          last_seen_at, expires_at
                        ) VALUES (
                          $1, $2, $3, $4, $5, $6, $7, $8, $8, $9
                        )
                        """,
                        session_id,
                        member.id,
                        token_family_id,
                        refresh_hash,
                        installation_id,
                        platform,
                        device_name,
                        issued_at,
                        refresh_expires_at,
                        )
            except asyncpg.UniqueViolationError as exc:
                if attempt + 1 == self._retry_attempts:
                    raise AuthenticationDependencyUnavailable from exc
                continue
            except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
                raise AuthenticationDependencyUnavailable from exc

            return IssuedSession(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in_seconds=int(self._access_delta.total_seconds()),
            )
        raise AuthenticationDependencyUnavailable
