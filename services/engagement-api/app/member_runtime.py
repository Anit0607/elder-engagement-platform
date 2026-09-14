from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

import asyncpg
from google.cloud.sql.connector import Connector, IPTypes

from app.authorization import SessionAuthorization
from app.config import ConfigurationError, Settings
from app.google_phone_identity import GooglePhoneIdentityVerifier
from app.member_auth import MemberSessionService
from app.postgres_member_repository import PostgresMemberRepository
from app.postgres_profiles import PostgresProfileService, verify_profile_schema
from app.postgres_staff_session import PostgresStaffSessionService
from app.session_refresh import PostgresSessionRefresh
from app.shared_session_controls import SharedSessionControls
from app.staff_credentials import StaffAuthenticator, StaffCredentialVerifier, StaffPasswords
from app.staff_schema import verify_staff_schema
from app.staff_session_controls import PostgresStaffSessionControls


def _session_secret(environ: Mapping[str, str], name: str) -> bytes:
    try:
        value = base64.b64decode(environ.get(name, ""), validate=True)
    except (ValueError, binascii.Error):
        raise ConfigurationError("Member session secret injection is invalid") from None
    if len(value) < 32:
        raise ConfigurationError("Member session secret injection is missing or too short")
    return value


@asynccontextmanager
async def member_runtime(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    connector_factory=Connector,
    pool_factory=asyncpg.create_pool,
):
    environment = os.environ if environ is None else environ
    signing_key = _session_secret(environment, "AMIKO_SESSION_SIGNING_KEY_BASE64")
    refresh_pepper = _session_secret(environment, "AMIKO_REFRESH_PEPPER_BASE64")
    authenticator_key = None
    if settings.staff_session_enabled:
        authenticator_key = _session_secret(environment, "AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64")
        if len(authenticator_key) != 32 or any(
            hmac.compare_digest(authenticator_key, other) for other in (signing_key, refresh_pepper)
        ):
            raise ConfigurationError("Staff authenticator key must be independent and exactly 32 bytes")
    verifier = GooglePhoneIdentityVerifier(settings.firebase_project_id, settings.member_token_audience)
    try:
        async with connector_factory(
            loop=asyncio.get_running_loop(),
            ip_type=IPTypes.PRIVATE,
            enable_iam_auth=True,
            refresh_strategy="LAZY",
            timeout=10,
        ) as connector:

            async def get_connection(instance, **kwargs):
                return await connector.connect_async(
                    instance,
                    "asyncpg",
                    user=settings.database_iam_user,
                    db="engagement",
                    enable_iam_auth=True,
                    ip_type=IPTypes.PRIVATE,
                    **kwargs,
                )

            async with pool_factory(
                settings.cloud_sql_instance,
                connect=get_connection,
                min_size=0,
                max_size=4,
                timeout=10,
                command_timeout=5,
                server_settings={
                    "application_name": "amiko-member-api",
                    "statement_timeout": "5000",
                    "lock_timeout": "3000",
                },
            ) as pool:
                sessions = PostgresSessionRefresh(
                    pool,
                    signing_key=signing_key,
                    refresh_pepper=refresh_pepper,
                    issuer=settings.public_api_origin,
                    access_token_minutes=settings.access_token_minutes,
                    refresh_token_days=settings.refresh_token_days,
                    member_session_limit=5,
                )
                handler = MemberSessionService(
                    verifier,
                    PostgresMemberRepository(pool),
                    sessions,
                    session_controls=sessions,
                )
                staff_controls = None
                if settings.staff_session_enabled:
                    await verify_staff_schema(pool)
                    options = dict(
                        signing_key=signing_key,
                        refresh_pepper=refresh_pepper,
                        issuer=settings.public_api_origin,
                        access_token_minutes=settings.access_token_minutes,
                        refresh_token_days=settings.refresh_token_days,
                    )
                    staff_controls = PostgresStaffSessionControls(pool, **options)
                    handler.staff_session_handler = PostgresStaffSessionService(
                        pool,
                        verifier=StaffCredentialVerifier(
                            StaffPasswords(), StaffAuthenticator(authenticator_key)
                        ),
                        **options,
                    )
                    handler.session_controls = SharedSessionControls(
                        pool,
                        sessions,
                        staff_controls,
                        refresh_pepper,
                    )
                if settings.profile_enabled:
                    await verify_profile_schema(pool)
                    handler.profile_service = PostgresProfileService(
                        SessionAuthorization(pool, sessions, staff_controls)
                    )
                yield handler
    finally:
        verifier.close()
