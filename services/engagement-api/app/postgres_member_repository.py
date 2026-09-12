from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from typing import Any

import asyncpg

from app.member_auth import (
    AuthenticationDependencyUnavailable,
    IdentityTokenRejected,
    MemberRecord,
)


def _default_public_id() -> str:
    return f"AMI-{secrets.token_hex(10).upper()}"


def _lock_key(namespace: str, value: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresMemberRepository:
    """Atomically find, activate or create a Member from a verified phone identity."""

    def __init__(
        self,
        pool: Any,
        *,
        public_id_factory: Callable[[], str] = _default_public_id,
        retry_attempts: int = 3,
    ) -> None:
        if not 1 <= retry_attempts <= 5:
            raise ValueError("retry attempts must be between one and five")
        self._pool = pool
        self._public_id_factory = public_id_factory
        self._retry_attempts = retry_attempts

    async def get_or_create_verified_member(
        self, phone_e164: str, provider_subject: str
    ) -> MemberRecord:
        for attempt in range(self._retry_attempts):
            try:
                return await self._get_or_create_once(phone_e164, provider_subject)
            except asyncpg.UniqueViolationError as exc:
                if attempt + 1 == self._retry_attempts:
                    raise AuthenticationDependencyUnavailable from exc
            except IdentityTokenRejected:
                raise
            except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
                raise AuthenticationDependencyUnavailable from exc
        raise AuthenticationDependencyUnavailable

    async def _get_or_create_once(
        self, phone_e164: str, provider_subject: str
    ) -> MemberRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                for key in sorted(
                    {
                        _lock_key("member-phone", phone_e164),
                        _lock_key("member-subject", provider_subject),
                    }
                ):
                    await connection.execute(
                        "SELECT pg_advisory_xact_lock($1::bigint)", key
                    )

                rows = await self._matching_members(
                    connection, phone_e164, provider_subject
                )
                if len(rows) > 1:
                    raise IdentityTokenRejected
                if rows:
                    row = rows[0]
                    if row["role"] != "member":
                        raise IdentityTokenRejected
                    existing_subject = row["identity_provider_subject"]
                    if existing_subject and existing_subject != provider_subject:
                        raise IdentityTokenRejected
                    identity_needs_update = (
                        row["phone_e164"] != phone_e164
                        or existing_subject != provider_subject
                    )
                    if identity_needs_update and row["status"] not in {
                        "active",
                        "invited",
                    }:
                        raise IdentityTokenRejected
                    if identity_needs_update or row["status"] == "invited":
                        await connection.execute(
                            """
                            UPDATE engagement_app.app_users
                               SET phone_e164 = $1,
                                   identity_provider_subject = $2,
                                   status = CASE
                                     WHEN status = 'invited' THEN 'active'::engagement_app.user_status
                                     ELSE status
                                   END,
                                   updated_at = now()
                             WHERE id = $3
                            """,
                            phone_e164,
                            provider_subject,
                            row["id"],
                        )
                    resolved = await self._member_by_id(connection, row["id"])
                    if resolved is None:
                        raise AuthenticationDependencyUnavailable
                    return self._to_member_record(resolved)

                created = await connection.fetchrow(
                    """
                    INSERT INTO engagement_app.app_users (
                      public_id, role, status, phone_e164, identity_provider_subject
                    )
                    VALUES ($1, 'member', 'active', $2, $3)
                    RETURNING id
                    """,
                    self._public_id_factory(),
                    phone_e164,
                    provider_subject,
                )
                resolved = await self._member_by_id(connection, created["id"])
                if resolved is None:
                    raise AuthenticationDependencyUnavailable
                return self._to_member_record(resolved)

    @staticmethod
    async def _matching_members(connection, phone_e164: str, provider_subject: str):
        return await connection.fetch(
            """
            SELECT u.id,
                   u.role::text AS role,
                   u.status::text AS status,
                   u.phone_e164,
                   u.identity_provider_subject,
                   u.created_at,
                   u.updated_at,
                   p.display_name,
                   p.preferred_language,
                   COALESCE(p.profile_complete, false) AS profile_complete
              FROM engagement_app.app_users AS u
              LEFT JOIN engagement_app.user_profiles AS p ON p.user_id = u.id
             WHERE u.phone_e164 = $1 OR u.identity_provider_subject = $2
             FOR UPDATE OF u
            """,
            phone_e164,
            provider_subject,
        )

    @staticmethod
    async def _member_by_id(connection, member_id):
        return await connection.fetchrow(
            """
            SELECT u.id,
                   u.role::text AS role,
                   u.status::text AS status,
                   u.phone_e164,
                   u.identity_provider_subject,
                   u.created_at,
                   u.updated_at,
                   p.display_name,
                   p.preferred_language,
                   COALESCE(p.profile_complete, false) AS profile_complete
              FROM engagement_app.app_users AS u
              LEFT JOIN engagement_app.user_profiles AS p ON p.user_id = u.id
             WHERE u.id = $1
            """,
            member_id,
        )

    @staticmethod
    def _to_member_record(row: Mapping[str, Any]) -> MemberRecord:
        return MemberRecord(
            id=row["id"],
            role=row["role"],
            status=row["status"],
            display_name=row["display_name"],
            preferred_language=row["preferred_language"],
            profile_complete=row["profile_complete"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
