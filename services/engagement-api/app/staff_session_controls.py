"""Staff session candidate; requires V0002/V0003 and is not runtime-enabled."""

from __future__ import annotations

import hmac
import re
from datetime import UTC, timedelta
from uuid import UUID, uuid4

import asyncpg
import jwt
from pydantic import ValidationError

from app.member_auth import MemberSessionFailure
from app.postgres_session_issuer import PostgresSessionIssuer
from app.session_controls import SessionSummary, denied
from app.session_refresh import invalid_refresh
from app.staff_auth import StaffSessionResponse, StaffUserSummary


class PostgresStaffSessionControls(PostgresSessionIssuer):
    def _claims(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 8192:
            raise denied()
        try:
            claims = jwt.decode(
                token,
                self._signing_key,
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["iss", "aud", "sub", "sid", "jti", "role", "cv", "iat", "nbf", "exp"],
                    "strict_aud": True,
                },
            )
            if (
                claims["role"] not in {"contributor", "administrator"}
                or any(type(claims[key]) is not int for key in ("iat", "nbf", "exp"))
                or not 0 < claims["exp"] - claims["iat"] <= self._access_delta.total_seconds()
                or claims["nbf"] != claims["iat"]
            ):
                raise ValueError
            for key in ("sub", "sid", "jti", "cv"):
                if not isinstance(claims[key], str) or str(UUID(claims[key])) != claims[key]:
                    raise ValueError
            return UUID(claims["sub"]), UUID(claims["sid"]), claims["role"], UUID(claims["cv"])
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
            raise denied() from exc

    def _clock(self):
        now = self._now()
        if now.utcoffset() is None:
            raise ValueError("Staff session clock must be timezone-aware")
        return now.astimezone(UTC)

    async def _account(self, connection, user_id):
        user = await connection.fetchrow(
            """SELECT id, role::text, status::text, created_at, updated_at
               FROM engagement_app.app_users WHERE id=$1 FOR UPDATE""",
            user_id,
        )
        if not user or user["role"] not in {"contributor", "administrator"}:
            raise denied()
        if user["status"] == "suspended":
            raise MemberSessionFailure(status=403, code="ACCOUNT_SUSPENDED", title="Account is suspended")
        if user["status"] != "active":
            raise denied()
        credential = await connection.fetchrow(
            """SELECT credential_version, second_factor_enabled, mfa_secret_ciphertext
               FROM engagement_app.staff_credentials WHERE user_id=$1 FOR UPDATE""",
            user_id,
        )
        if not credential or (
            user["role"] == "administrator"
            and (not credential["second_factor_enabled"] or credential["mfa_secret_ciphertext"] is None)
        ):
            raise denied()
        return user, credential["credential_version"]

    async def _operate(self, token, action, target=None):
        user_id, session_id, role, version = self._claims(token)
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                user, current_version = await self._account(connection, user_id)
                if role != user["role"] or version != current_version:
                    raise denied()
                now = self._clock()
                session = await connection.fetchrow(
                    """SELECT token_family_id FROM engagement_app.auth_sessions
                       WHERE id=$1 AND user_id=$2 AND staff_credential_version=$3
                         AND revoked_at IS NULL AND replaced_by_session_id IS NULL
                         AND expires_at>$4 FOR UPDATE""",
                    session_id,
                    user_id,
                    version,
                    now,
                )
                if not session:
                    raise denied()
                await connection.execute(
                    "UPDATE engagement_app.auth_sessions SET last_seen_at=$2 WHERE id=$1",
                    session_id,
                    now,
                )
                if action == "list":
                    rows = await connection.fetch(
                        """SELECT id, installation_id, platform, device_name, created_at, last_seen_at
                           FROM engagement_app.auth_sessions WHERE user_id=$1 AND staff_credential_version=$2
                             AND revoked_at IS NULL AND replaced_by_session_id IS NULL AND expires_at>$3
                           ORDER BY created_at DESC, id""",
                        user_id,
                        version,
                        now,
                    )
                    return [SessionSummary(**dict(row), current=row["id"] == session_id) for row in rows]
                family = session["token_family_id"]
                if action == "revoke":
                    selected = await connection.fetchrow(
                        """SELECT token_family_id FROM engagement_app.auth_sessions
                           WHERE id=$1 AND user_id=$2 AND staff_credential_version=$3
                             AND revoked_at IS NULL AND replaced_by_session_id IS NULL
                             AND expires_at>$4 FOR UPDATE""",
                        target,
                        user_id,
                        version,
                        now,
                    )
                    if not selected:
                        raise MemberSessionFailure(status=404, code="NOT_FOUND", title="Resource not found")
                    family = selected["token_family_id"]
                await connection.execute(
                    """UPDATE engagement_app.auth_sessions SET revoked_at=$3
                       WHERE user_id=$1 AND token_family_id=$2 AND revoked_at IS NULL""",
                    user_id,
                    family,
                    now,
                )
        except (asyncpg.PostgresError, OSError, TimeoutError, ValidationError) as exc:
            raise self._unavailable() from exc

    @staticmethod
    def _unavailable():
        # Including removal: acknowledgement can be lost after a successful commit.
        return MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Staff session service is temporarily unavailable",
            retryable=False,
        )

    async def list_sessions(self, token):
        return await self._operate(token, "list")

    async def logout(self, token):
        await self._operate(token, "logout")

    async def revoke(self, token, target):
        await self._operate(token, "revoke", target)

    async def refresh(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"amr1_[A-Za-z0-9_-]{64}", token):
            raise invalid_refresh()
        token_hash = hmac.digest(self._refresh_pepper, token.encode(), "sha256").hex()
        failure = None
        result = None
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                owner = await connection.fetchrow(
                    "SELECT user_id FROM engagement_app.auth_sessions WHERE refresh_token_hash=$1",
                    token_hash,
                )
                if not owner:
                    raise invalid_refresh()
                user, version = await self._account(connection, owner["user_id"])
                now = self._clock()
                session = await connection.fetchrow(
                    """SELECT id, token_family_id, installation_id, platform, device_name, expires_at,
                              revoked_at, replaced_by_session_id, staff_credential_version
                       FROM engagement_app.auth_sessions
                       WHERE refresh_token_hash=$1 AND user_id=$2 FOR UPDATE""",
                    token_hash,
                    user["id"],
                )
                if not session or session["staff_credential_version"] != version:
                    raise invalid_refresh()
                if session["revoked_at"] is not None:
                    raise MemberSessionFailure(status=401, code="SESSION_REVOKED", title="Sign in again")
                if session["replaced_by_session_id"] is not None:
                    await connection.execute(
                        """UPDATE engagement_app.auth_sessions SET revoked_at=$3
                           WHERE user_id=$1 AND token_family_id=$2 AND revoked_at IS NULL""",
                        user["id"],
                        session["token_family_id"],
                        now,
                    )
                    failure = MemberSessionFailure(
                        status=409, code="REFRESH_TOKEN_REUSED", title="Sign in again"
                    )
                else:
                    expires = min(now + self._access_delta, session["expires_at"])
                    if expires - now < timedelta(seconds=60):
                        raise invalid_refresh()
                    profile = await connection.fetchrow(
                        """SELECT display_name, preferred_language, profile_complete
                           FROM engagement_app.user_profiles WHERE user_id=$1""",
                        user["id"],
                    )
                    new_id = uuid4()
                    tokens, new_hash = self._tokens(
                        user["id"], new_id, now, expires, role=user["role"], credential_version=version
                    )
                    result = StaffSessionResponse(
                        access_token=tokens.access_token,
                        refresh_token=tokens.refresh_token,
                        expires_in_seconds=tokens.expires_in_seconds,
                        user=StaffUserSummary(
                            **dict(user),
                            display_name=profile["display_name"] if profile else None,
                            preferred_language=profile["preferred_language"] if profile else None,
                            profile_complete=profile["profile_complete"] if profile else False,
                        ),
                    )
                    await connection.execute(
                        """INSERT INTO engagement_app.auth_sessions
                           (id,user_id,token_family_id,refresh_token_hash,installation_id,platform,device_name,
                            created_at,last_seen_at,expires_at,staff_credential_version)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8,$9,$10)""",
                        new_id,
                        user["id"],
                        session["token_family_id"],
                        new_hash,
                        session["installation_id"],
                        session["platform"],
                        session["device_name"],
                        now,
                        session["expires_at"],
                        version,
                    )
                    await connection.execute(
                        """UPDATE engagement_app.auth_sessions SET replaced_by_session_id=$2,last_seen_at=$3
                           WHERE id=$1""",
                        session["id"],
                        new_id,
                        now,
                    )
        except (asyncpg.PostgresError, OSError, TimeoutError, ValidationError) as exc:
            raise self._unavailable() from exc
        # Replay revocation must commit before the rejection is returned.
        if failure:
            raise failure
        if result is None:
            raise invalid_refresh()
        return result
