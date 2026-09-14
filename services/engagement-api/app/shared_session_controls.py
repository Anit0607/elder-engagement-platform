"""One REST session interface; each role adapter independently authenticates."""

from __future__ import annotations

import hmac
import re

import asyncpg

from app.member_auth import MemberSessionFailure
from app.session_refresh import invalid_refresh


class SharedSessionControls:
    def __init__(self, pool, member, staff, refresh_pepper):
        self._pool, self._member, self._staff = pool, member, staff
        self._refresh_pepper = refresh_pepper

    def _access_adapter(self, token):
        try:
            self._member._claims(token)
            return self._member
        except MemberSessionFailure:
            # Never dispatch based on unverified token contents or a posted role.
            self._staff._claims(token)
            return self._staff

    async def refresh(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"amr1_[A-Za-z0-9_-]{64}", token):
            raise invalid_refresh()
        token_hash = hmac.digest(self._refresh_pepper, token.encode(), "sha256").hex()
        try:
            async with self._pool.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT staff_credential_version FROM engagement_app.auth_sessions
                       WHERE refresh_token_hash=$1""",
                    token_hash,
                )
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Session service is temporarily unavailable",
                retryable=False,
            ) from exc
        if not row:
            raise invalid_refresh()
        adapter = self._staff if row["staff_credential_version"] is not None else self._member
        # The adapter rechecks current authoritative user/credential/session state
        # inside its own transaction; this routing read grants no authorization.
        return await adapter.refresh(token)

    async def list_sessions(self, token):
        return await self._access_adapter(token).list_sessions(token)

    async def logout(self, token):
        await self._access_adapter(token).logout(token)

    async def revoke(self, token, target):
        await self._access_adapter(token).revoke(token, target)
