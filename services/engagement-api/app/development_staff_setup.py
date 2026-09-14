"""Fictional staff setup job candidate. Not an HTTP route or production tool.

Cloud infrastructure, secure inputs and the reviewed execution process must be
prepared separately. Generated authenticator codes are ONLY for fictional
fixture preparation; they do not count as client authenticator acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyotp
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.authorization import SessionAuthorization
from app.config import ConfigurationError, load_settings
from app.member_auth import MemberSessionFailure
from app.member_runtime import _session_secret, member_runtime
from app.postgres_staff_session import PostgresStaffSessionService
from app.session_controls import denied
from app.staff_auth import StaffSessionRequest
from app.staff_credentials import StaffAuthenticator, StaffCredentialVerifier, StaffPasswords
from app.staff_enrollment import PostgresStaffEnrollment, StaffEnrollmentRequest
from app.staff_session_controls import PostgresStaffSessionControls


class FictionalSetupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    administrator_password: SecretStr = Field(min_length=12, max_length=256, repr=False)
    contributor_password: SecretStr = Field(min_length=12, max_length=256, repr=False)
    administrator_seed: SecretStr = Field(min_length=32, max_length=32, repr=False)


class BoundPool:
    """Nested operations share one transaction/connection; no partial fixture."""

    def __init__(self, connection):
        self._connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self._connection


class RejectMemberProof:
    def _claims(self, token):
        raise denied()


def guard_job(settings, environment):
    expected_job = "ee-development-fictional-staff-setup"
    if (
        settings.environment != "development"
        or not settings.staff_session_enabled
        or environment.get("STAFF_SETUP_MODE") != "fictional-development"
        or environment.get("STAFF_SETUP_PROJECT") != settings.gcp_project_id
        or environment.get("CLOUD_RUN_JOB") != expected_job
        or not environment.get("CLOUD_RUN_EXECUTION")
        or not re.fullmatch(r"[0-9a-f]{40}", environment.get("SOURCE_REVISION", ""))
    ):
        raise ConfigurationError("Reviewed fictional development job required")


async def create_fictional_fixture(
    pool, inputs, passwords, authenticator, options, *, now=lambda: datetime.now(UTC)
):
    seed = inputs.administrator_seed.get_secret_value()
    if not re.fullmatch(r"[A-Z2-7]{32}", seed):
        raise ConfigurationError("Fictional authenticator input is invalid")
    checks = []
    async with pool.acquire() as connection, connection.transaction():
        bound = BoundPool(connection)
        staff = PostgresStaffSessionService(
            bound, verifier=StaffCredentialVerifier(passwords, authenticator), now=now, **options
        )
        controls = PostgresStaffSessionControls(bound, now=now, **options)
        authorization = SessionAuthorization(bound, RejectMemberProof(), controls, now=now)
        enrollment = PostgresStaffEnrollment(bound, authorization, passwords, authenticator, now=now)
        # Use the previous allowed window for fixture confirmation, then a fresh
        # current-window code for login. No sleeps or fabricated clock changes.
        admin_request = StaffEnrollmentRequest(
            username="fictional.ee010.administrator",
            password=inputs.administrator_password,
            displayName="Fictional staff test",
            preferredLanguage="en",
            role="administrator",
            authenticatorSeed=inputs.administrator_seed,
            authenticatorCode=pyotp.TOTP(seed).at(now() - timedelta(seconds=30)),
        )
        admin = await enrollment.bootstrap_development_administrator(
            admin_request,
            "fictional-staff-setup",
            environment="development",
            confirmation="BOOTSTRAP-FIRST-DEVELOPMENT-ADMINISTRATOR",
        )
        admin_session = await staff.create(
            StaffSessionRequest(
                username=admin_request.username,
                password=inputs.administrator_password,
                secondFactorCode=pyotp.TOTP(seed).at(now()),
                installationId=uuid4(),
                platform="web",
            )
        )
        if admin_session.user.id != admin.id or admin_session.user.role != "administrator":
            raise ConfigurationError("Fictional Administrator verification failed")
        checks.append("fictional_administrator_enrolled_and_two_factor_login_verified")
        contributor_request = StaffEnrollmentRequest(
            username="fictional.ee010.contributor",
            password=inputs.contributor_password,
            displayName="Fictional staff test",
            preferredLanguage="en",
            role="contributor",
        )
        contributor = await enrollment.create_contributor(
            admin_session.access_token, contributor_request, "fictional-staff-setup"
        )
        contributor_session = await staff.create(
            StaffSessionRequest(
                username=contributor_request.username,
                password=inputs.contributor_password,
                installationId=uuid4(),
                platform="ios",
            )
        )
        if contributor_session.user.id != contributor.id or contributor_session.user.role != "contributor":
            raise ConfigurationError("Fictional Contributor verification failed")
        checks.append("administrator_created_contributor_password_login_verified")
        try:
            await enrollment.create_contributor(
                contributor_session.access_token, contributor_request, "fictional-staff-setup"
            )
        except MemberSessionFailure as error:
            if error.status != 403:
                raise ConfigurationError("Fictional Contributor permission check failed") from error
        else:
            raise ConfigurationError("Fictional Contributor was given Administrator permission")
        checks.append("contributor_cannot_create_staff")
        await controls.logout(contributor_session.access_token)
        await controls.logout(admin_session.access_token)
        checks.append("setup_test_sessions_signed_out")
    return checks


async def run(environment=None):
    values = os.environ if environment is None else environment
    settings = load_settings(values)
    guard_job(settings, values)
    raw = values.get("AMIKO_FICTIONAL_STAFF_SETUP_INPUT", "")
    if not raw or len(raw) > 4096:
        raise ConfigurationError("Pinned private fictional input is required")
    inputs = FictionalSetupInput.model_validate_json(raw)
    key = _session_secret(values, "AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64")
    signing = _session_secret(values, "AMIKO_SESSION_SIGNING_KEY_BASE64")
    pepper = _session_secret(values, "AMIKO_REFRESH_PEPPER_BASE64")
    options = dict(
        signing_key=signing,
        refresh_pepper=pepper,
        issuer=settings.public_api_origin,
        access_token_minutes=settings.access_token_minutes,
        refresh_token_days=settings.refresh_token_days,
    )
    # Runtime enforces private IAM database access, independent key and metadata.
    async with member_runtime(settings, environ=values) as handler:
        checks = await create_fictional_fixture(
            handler.staff_session_handler._pool, inputs, StaffPasswords(), StaffAuthenticator(key), options
        )
    return {
        "status": "ok",
        "checks": checks,
        "fictional_only": True,
        "client_authenticator_acceptance": False,
        "public_route_enabled": False,
    }


def main():
    try:
        result = asyncio.run(run())
    except Exception:
        # Do not print exception values, JSON inputs, tokens, hashes or seeds.
        print(
            json.dumps(
                {"status": "failed", "reason": "Fictional staff setup stopped; private details suppressed"}
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
