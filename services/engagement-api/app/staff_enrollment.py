"""Controlled staff enrollment foundation; no HTTP route or cloud job is wired.

Contributors require a current Administrator session. The first Administrator
bootstrap is development-only and must be called by a separately controlled
Google Cloud operation, never by a public app request. It refuses a second
bootstrap even if the existing Administrator is suspended or deleted.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.account_controls import AccountSummary, conflict
from app.authorization import Permission
from app.member_auth import MemberSessionFailure
from app.staff_credentials import (
    CredentialProtectionUnavailable,
    PasswordCapacityUnavailable,
    StaffAuthenticator,
    StaffPasswords,
)


class StaffEnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)
    username: str = Field(strict=True, min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    password: SecretStr = Field(min_length=12, max_length=256, repr=False)
    display_name: str = Field(alias="displayName", strict=True, min_length=1, max_length=120)
    preferred_language: Literal["en", "bn", "hi"] = Field(alias="preferredLanguage")
    role: Literal["contributor", "administrator"]
    authenticator_seed: SecretStr | None = Field(default=None, alias="authenticatorSeed", repr=False)
    authenticator_code: SecretStr | None = Field(default=None, alias="authenticatorCode", repr=False)

    @model_validator(mode="after")
    def check_enrollment(self):
        import re

        if not self.display_name.strip():
            raise ValueError("A display name is required")
        if self.role == "contributor":
            if self.authenticator_seed is not None or self.authenticator_code is not None:
                raise ValueError("Contributor enrollment uses a password only")
        elif (
            self.authenticator_seed is None
            or self.authenticator_code is None
            or not re.fullmatch(r"[A-Z2-7]{32}", self.authenticator_seed.get_secret_value())
            or not re.fullmatch(r"[0-9]{6}", self.authenticator_code.get_secret_value())
        ):
            raise ValueError("Administrator enrollment needs an authenticator and confirmation code")
        return self


class PostgresStaffEnrollment:
    def __init__(
        self,
        pool,
        authorization,
        passwords: StaffPasswords,
        authenticator: StaffAuthenticator,
        *,
        now=lambda: datetime.now(UTC),
    ):
        self._pool, self._authorization = pool, authorization
        self._passwords, self._authenticator, self._now = passwords, authenticator, now

    async def _insert(self, connection, request, *, actor, action, trace):
        user_id = uuid4()
        now = self._now()
        if now.utcoffset() is None:
            raise ValueError("Enrollment clock must be timezone-aware")
        now = now.astimezone(UTC)
        try:
            password_hash = await asyncio.to_thread(self._passwords.hash, request.password.get_secret_value())
            ciphertext, step = None, None
            if request.role == "administrator":
                ciphertext = self._authenticator.protect(
                    user_id, request.authenticator_seed.get_secret_value()
                )
                # Confirm at the end of hashing, not against a stale pre-hash clock.
                step = self._authenticator.matched_step(
                    user_id, ciphertext, request.authenticator_code.get_secret_value(), self._now(), None
                )
                if step is None:
                    raise MemberSessionFailure(
                        status=401, code="AUTHENTICATION_FAILED", title="Authenticator confirmation failed"
                    )
        except PasswordCapacityUnavailable as exc:
            raise MemberSessionFailure(
                status=429, code="RATE_LIMITED", title="Wait before trying again"
            ) from exc
        except CredentialProtectionUnavailable as exc:
            raise MemberSessionFailure(
                status=503, code="DEPENDENCY_UNAVAILABLE", title="Account setup protection is unavailable"
            ) from exc
        # Validate the public result before any write. No secret is returned.
        result = AccountSummary(
            id=user_id,
            role=request.role,
            status="active",
            display_name=request.display_name,
            preferred_language=request.preferred_language,
            profile_complete=True,
            created_at=now,
            updated_at=now,
        )
        await connection.execute(
            """INSERT INTO engagement_app.app_users (id,public_id,role,status,username,created_at,updated_at)
               VALUES($1,$2,$3,'active',$4,$5,$5)""",
            user_id,
            "AMI-" + uuid4().hex[:24],
            request.role,
            request.username,
            now,
        )
        await connection.execute(
            """INSERT INTO engagement_app.staff_credentials
               (user_id,password_hash,second_factor_enabled,mfa_secret_ciphertext,last_accepted_totp_step)
               VALUES($1,$2,$3,$4,$5)""",
            user_id,
            password_hash,
            request.role == "administrator",
            ciphertext,
            step,
        )
        await connection.execute(
            """INSERT INTO engagement_app.user_profiles
               (user_id,display_name,preferred_language,profile_complete,created_at,updated_at)
               VALUES($1,$2,$3,true,$4,$4)""",
            user_id,
            request.display_name,
            request.preferred_language,
            now,
        )
        await connection.execute(
            """INSERT INTO engagement_app.audit_events
               (actor_user_id,action,entity_type,entity_id,trace_id,metadata)
               VALUES($1,$2,'app_user',$3,$4,$5::jsonb)""",
            actor,
            action,
            str(user_id),
            trace,
            json.dumps({"role": request.role, "authenticatorConfirmed": step is not None}),
        )
        return result

    async def create_contributor(self, token, request: StaffEnrollmentRequest, trace):
        if request.role != "contributor":
            raise MemberSessionFailure(
                status=403, code="FORBIDDEN", title="Use a separate Administrator setup"
            )
        try:
            async with self._authorization.transaction(token, Permission.CREATE_STAFF) as (
                connection,
                principal,
            ):
                return await self._insert(
                    connection, request, actor=principal.user_id, action="contributor.created", trace=trace
                )
        except asyncpg.UniqueViolationError as exc:
            raise conflict() from exc

    async def bootstrap_development_administrator(
        self, request: StaffEnrollmentRequest, trace, *, environment, confirmation
    ):
        if environment != "development" or confirmation != "BOOTSTRAP-FIRST-DEVELOPMENT-ADMINISTRATOR":
            raise MemberSessionFailure(
                status=403, code="FORBIDDEN", title="Controlled development setup required"
            )
        if request.role != "administrator":
            raise MemberSessionFailure(
                status=400, code="VALIDATION_FAILED", title="Administrator setup required"
            )
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(704193041901::bigint)")
                exists = await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM engagement_app.app_users WHERE role='administrator')"
                )
                if exists is not False:
                    raise conflict()
                return await self._insert(
                    connection, request, actor=None, action="administrator.development_bootstrap", trace=trace
                )
        except asyncpg.UniqueViolationError as exc:
            raise conflict() from exc
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            # Never retry an uncertain commit automatically or reset an existing account.
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Account setup is temporarily unavailable",
                retryable=False,
            ) from exc
