from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.member_auth import AuthenticationDependencyUnavailable, IdentityTokenRejected
from app.postgres_member_repository import PostgresMemberRepository, _lock_key

PHONE = "+919999999901"
SUBJECT = "synthetic-provider-subject"
NOW = datetime(2026, 9, 12, tzinfo=UTC)


class AsyncContext(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeConnection:
    def __init__(self, users=None, profiles=None, insert_failures=0, fetch_failure=None):
        self.users = list(users or [])
        self.profiles = dict(profiles or {})
        self.insert_failures = insert_failures
        self.fetch_failure = fetch_failure
        self.lock_keys = []

    def transaction(self):
        return AsyncContext(self)

    async def execute(self, query, *values):
        if "pg_advisory_xact_lock" in query:
            self.lock_keys.append(values[0])
            return "SELECT 1"
        if "UPDATE engagement_app.app_users" in query:
            phone, subject, member_id = values
            user = next(item for item in self.users if item["id"] == member_id)
            user["phone_e164"] = phone
            user["identity_provider_subject"] = subject
            if user["status"] == "invited":
                user["status"] = "active"
            user["updated_at"] = NOW
            return "UPDATE 1"
        raise AssertionError("unexpected SQL")

    async def fetch(self, query, phone, subject):
        del query
        if self.fetch_failure:
            raise self.fetch_failure
        return [
            self._joined(user)
            for user in self.users
            if user["phone_e164"] == phone
            or user["identity_provider_subject"] == subject
        ]

    async def fetchrow(self, query, *values):
        if "INSERT INTO" in query:
            if self.insert_failures:
                self.insert_failures -= 1
                raise asyncpg.UniqueViolationError("synthetic collision")
            public_id, phone, subject = values
            member_id = uuid4()
            self.users.append(
                user_row(
                    id=member_id,
                    public_id=public_id,
                    phone_e164=phone,
                    identity_provider_subject=subject,
                    status="active",
                )
            )
            return {"id": member_id}
        member_id = values[0]
        user = next((item for item in self.users if item["id"] == member_id), None)
        return self._joined(user) if user else None

    def _joined(self, user):
        profile = self.profiles.get(user["id"], {})
        return {
            **user,
            "display_name": profile.get("display_name"),
            "preferred_language": profile.get("preferred_language"),
            "profile_complete": profile.get("profile_complete", False),
        }


class FakePool:
    def __init__(self, connection):
        self.connection = connection
        self.acquisitions = 0

    def acquire(self):
        self.acquisitions += 1
        return AsyncContext(self.connection)


def user_row(**overrides):
    row = {
        "id": uuid4(),
        "public_id": "AMI-TEST-MEMBER",
        "role": "member",
        "status": "active",
        "phone_e164": PHONE,
        "identity_provider_subject": SUBJECT,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(overrides)
    return row


@pytest.mark.anyio
async def test_new_verified_identity_creates_one_active_incomplete_member():
    connection = FakeConnection()
    repository = PostgresMemberRepository(
        FakePool(connection), public_id_factory=lambda: "AMI-SYNTHETIC-001"
    )
    member = await repository.get_or_create_verified_member(PHONE, SUBJECT)
    assert member.role == "member"
    assert member.status == "active"
    assert member.profile_complete is False
    assert connection.users[0]["public_id"] == "AMI-SYNTHETIC-001"
    assert connection.lock_keys == sorted(
        {_lock_key("member-phone", PHONE), _lock_key("member-subject", SUBJECT)}
    )


@pytest.mark.anyio
async def test_precreated_member_is_bound_activated_and_keeps_completed_profile():
    member_id = uuid4()
    existing = user_row(
        id=member_id,
        status="invited",
        identity_provider_subject=None,
    )
    connection = FakeConnection(
        [existing],
        {
            member_id: {
                "display_name": "Synthetic Member",
                "preferred_language": "bn",
                "profile_complete": True,
            }
        },
    )
    member = await PostgresMemberRepository(FakePool(connection)).get_or_create_verified_member(
        PHONE, SUBJECT
    )
    assert member.id == member_id
    assert member.status == "active"
    assert member.display_name == "Synthetic Member"
    assert member.preferred_language == "bn"
    assert member.profile_complete is True
    assert existing["identity_provider_subject"] == SUBJECT


@pytest.mark.anyio
@pytest.mark.parametrize(
    "users",
    [
        [user_row(role="contributor")],
        [user_row(identity_provider_subject="another-subject")],
        [user_row(status="suspended", phone_e164="+919999999902")],
        [
            user_row(identity_provider_subject="another-subject"),
            user_row(phone_e164="+919999999902"),
        ],
    ],
)
async def test_staff_or_conflicting_identity_is_never_claimed(users):
    with pytest.raises(IdentityTokenRejected):
        await PostgresMemberRepository(FakePool(FakeConnection(users))).get_or_create_verified_member(
            PHONE, SUBJECT
        )


@pytest.mark.anyio
async def test_unique_collision_retries_the_whole_transaction():
    connection = FakeConnection(insert_failures=1)
    pool = FakePool(connection)
    member = await PostgresMemberRepository(
        pool, public_id_factory=lambda: "AMI-SYNTHETIC-RETRY"
    ).get_or_create_verified_member(PHONE, SUBJECT)
    assert isinstance(member.id, UUID)
    assert pool.acquisitions == 2


@pytest.mark.anyio
async def test_database_failure_is_reported_as_retryable_dependency_failure():
    failure = asyncpg.CannotConnectNowError("synthetic database outage")
    connection = FakeConnection(fetch_failure=failure)
    with pytest.raises(AuthenticationDependencyUnavailable):
        await PostgresMemberRepository(FakePool(connection)).get_or_create_verified_member(
            PHONE, SUBJECT
        )


def test_repository_retry_limit_is_bounded():
    with pytest.raises(ValueError, match="between one and five"):
        PostgresMemberRepository(FakePool(FakeConnection()), retry_attempts=0)
