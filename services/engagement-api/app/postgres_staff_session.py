"""EE-010 transactional staff sign-in candidate; runtime remains disabled.

Staff session controls/renewal and secure enrollment must be connected before
activation. No client-provided role, password hash or encryption key is trusted.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
from pydantic import ValidationError

from app.member_auth import MemberSessionFailure
from app.postgres_session_issuer import PostgresSessionIssuer
from app.staff_auth import StaffSessionRequest, StaffSessionResponse, StaffUserSummary
from app.staff_credentials import StaffCredentialRecord, StaffCredentialVerifier


class PostgresStaffSessionService(PostgresSessionIssuer):
    def __init__(self, pool: Any, *, verifier: StaffCredentialVerifier, **kwargs):
        super().__init__(pool, **kwargs)
        self._verifier = verifier

    async def create(self, request: StaffSessionRequest) -> StaffSessionResponse:
        failure = None
        response = None
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    # Same order as Member session operations and baseline role guards.
                    # Username comparison is exact; there is no self-registration here.
                    owner = await connection.fetchrow(
                        """SELECT id, role::text, status::text, created_at, updated_at
                           FROM engagement_app.app_users WHERE username=$1 FOR UPDATE""",
                        request.username,
                    )
                    stored = None
                    if owner and owner["role"] in {"contributor", "administrator"}:
                        stored = await connection.fetchrow(
                            """SELECT * FROM engagement_app.staff_credentials
                               WHERE user_id=$1 FOR UPDATE""",
                            owner["id"],
                        )
                    now = self._now()
                    if now.utcoffset() is None:
                        raise ValueError("Staff sign-in clock must be timezone-aware")
                    now = now.astimezone(UTC)
                    record = None
                    if stored:
                        record = StaffCredentialRecord(
                            user_id=owner["id"],
                            role=owner["role"],
                            status=owner["status"],
                            password_hash=stored["password_hash"],
                            second_factor_enabled=stored["second_factor_enabled"],
                            encrypted_seed=stored["mfa_secret_ciphertext"],
                            last_accepted_step=stored["last_accepted_totp_step"],
                            locked_until=stored["locked_until"],
                        )
                    try:
                        matched = await self._verifier.verify(record, request, now)
                    except MemberSessionFailure as exc:
                        failure = exc
                        if stored and owner["status"] == "active" and exc.code == "AUTHENTICATION_FAILED":
                            # Expired lock starts a fresh attempt window. Commit this
                            # record before returning an error; raising here rolls it back.
                            previous = stored["failed_attempts"]
                            if stored["locked_until"] and stored["locked_until"] <= now:
                                previous = 0
                            attempts = min(previous + 1, 5)
                            await connection.execute(
                                """UPDATE engagement_app.staff_credentials
                                   SET failed_attempts=$2, locked_until=$3 WHERE user_id=$1""",
                                owner["id"],
                                attempts,
                                now + timedelta(minutes=10) if attempts >= 5 else None,
                            )
                    else:
                        # Verification returns only for an authoritative active staff row.
                        recent = await connection.fetchval(
                            """SELECT count(*) FROM engagement_app.auth_sessions AS candidate
                               WHERE user_id=$1 AND created_at >= $2 AND NOT EXISTS (
                                 SELECT 1 FROM engagement_app.auth_sessions AS previous
                                 WHERE previous.replaced_by_session_id=candidate.id)""",
                            owner["id"],
                            now - timedelta(minutes=10),
                        )
                        if recent >= 5:
                            failure = MemberSessionFailure(
                                status=429,
                                code="RATE_LIMITED",
                                title="Wait before signing in again",
                            )
                        else:
                            profile = await connection.fetchrow(
                                """SELECT display_name, preferred_language, profile_complete
                                   FROM engagement_app.user_profiles WHERE user_id=$1""",
                                owner["id"],
                            )
                            session_id = uuid4()
                            tokens, refresh_hash = self._tokens(
                                owner["id"],
                                session_id,
                                now,
                                now + self._access_delta,
                                role=owner["role"],
                                credential_version=stored["credential_version"],
                            )
                            response = StaffSessionResponse(
                                access_token=tokens.access_token,
                                refresh_token=tokens.refresh_token,
                                expires_in_seconds=tokens.expires_in_seconds,
                                user=StaffUserSummary(
                                    id=owner["id"],
                                    role=owner["role"],
                                    status="active",
                                    display_name=profile["display_name"] if profile else None,
                                    preferred_language=profile["preferred_language"] if profile else None,
                                    profile_complete=profile["profile_complete"] if profile else False,
                                    created_at=owner["created_at"],
                                    updated_at=owner["updated_at"],
                                ),
                            )
                            await connection.execute(
                                """UPDATE engagement_app.staff_credentials
                                   SET failed_attempts=0, locked_until=NULL,
                                       last_accepted_totp_step=$2 WHERE user_id=$1""",
                                owner["id"],
                                matched,
                            )
                            await connection.execute(
                                """INSERT INTO engagement_app.auth_sessions
                                   (id, user_id, token_family_id, refresh_token_hash,
                                    installation_id, platform, device_name, created_at,
                                    last_seen_at, expires_at, staff_credential_version)
                                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8,$9,$10)""",
                                session_id,
                                owner["id"],
                                uuid4(),
                                refresh_hash,
                                request.installation_id,
                                request.platform,
                                request.device_name,
                                now,
                                now + self._refresh_delta,
                                stored["credential_version"],
                            )
        except (asyncpg.PostgresError, OSError, TimeoutError, ValidationError) as exc:
            # A commit may have succeeded even if its acknowledgement was lost.
            # Never automatically replay a password/code submission after this error.
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Staff sign-in is temporarily unavailable",
                retryable=False,
            ) from exc
        if failure:
            raise failure
        if response is None:
            raise RuntimeError("Staff sign-in produced no outcome")
        return response
