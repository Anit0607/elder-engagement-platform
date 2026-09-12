from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import create_app
from app.member_auth import (
    AuthenticationDependencyUnavailable,
    IdentityTokenRejected,
    IssuedSession,
    MemberRecord,
    MemberSessionService,
    VerifiedPhoneIdentity,
)

MEMBER_ID = UUID("11111111-1111-4111-8111-111111111111")
INSTALLATION_ID = "22222222-2222-4222-8222-222222222222"
PROVIDER_TOKEN = "synthetic-provider-token-not-a-real-secret"  # noqa: S105 - inert test value
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


class FakeVerifier:
    def __init__(self, *, failure: Exception | None = None, phone: str = "+919999999901"):
        self.failure = failure
        self.phone = phone

    async def verify(self, provider_id_token: str) -> VerifiedPhoneIdentity:
        assert provider_id_token == PROVIDER_TOKEN
        if self.failure:
            raise self.failure
        return VerifiedPhoneIdentity(self.phone, "synthetic-provider-subject")


class FakeRepository:
    def __init__(self, member: MemberRecord, *, unavailable: bool = False):
        self.member = member
        self.unavailable = unavailable
        self.calls = 0

    async def get_or_create_verified_member(
        self, phone_e164: str, provider_subject: str
    ) -> MemberRecord:
        assert phone_e164 == "+919999999901"
        assert provider_subject == "synthetic-provider-subject"
        self.calls += 1
        if self.unavailable:
            raise AuthenticationDependencyUnavailable
        return self.member


class ConflictingRepository:
    async def get_or_create_verified_member(self, phone_e164, provider_subject):
        del phone_e164, provider_subject
        raise IdentityTokenRejected


class FakeIssuer:
    def __init__(self, *, unavailable: bool = False):
        self.unavailable = unavailable

    async def issue(self, member, installation_id, platform, device_name) -> IssuedSession:
        assert member.id == MEMBER_ID
        assert str(installation_id) == INSTALLATION_ID
        assert platform == "android"
        assert device_name == "Synthetic Android"
        if self.unavailable:
            raise AuthenticationDependencyUnavailable
        return IssuedSession("synthetic-access-token", "synthetic-refresh-token", 900)


def member(
    *,
    role: str = "member",
    status: str = "active",
    display_name: str | None = "Synthetic Member",
    preferred_language: str | None = "bn",
    profile_complete: bool = True,
) -> MemberRecord:
    return MemberRecord(
        id=MEMBER_ID,
        role=role,
        status=status,
        display_name=display_name,
        preferred_language=preferred_language,
        profile_complete=profile_complete,
        created_at=NOW,
        updated_at=NOW,
    )


def payload() -> dict[str, str]:
    return {
        "providerIdToken": PROVIDER_TOKEN,
        "installationId": INSTALLATION_ID,
        "platform": "android",
        "deviceName": "Synthetic Android",
    }


def make_client(settings, ready_probes, verifier, repository, issuer=None) -> TestClient:
    handler = MemberSessionService(verifier, repository, issuer or FakeIssuer())
    return TestClient(create_app(settings, ready_probes, member_session_handler=handler))


def test_verified_returning_member_receives_contract_session(settings, ready_probes):
    with make_client(settings, ready_probes, FakeVerifier(), FakeRepository(member())) as client:
        response = client.post("/v1/auth/member/session", json=payload())
    assert response.status_code == 200
    assert response.json() == {
        "accessToken": "synthetic-access-token",
        "refreshToken": "synthetic-refresh-token",
        "tokenType": "Bearer",
        "expiresInSeconds": 900,
        "user": {
            "id": str(MEMBER_ID),
            "role": "member",
            "status": "active",
            "displayName": "Synthetic Member",
            "preferredLanguage": "bn",
            "profileComplete": True,
            "createdAt": "2026-09-12T12:00:00Z",
            "updatedAt": "2026-09-12T12:00:00Z",
        },
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_invalid_or_unverified_provider_identity_is_rejected(settings, ready_probes):
    cases = [
        (FakeVerifier(failure=IdentityTokenRejected()), FakeRepository(member())),
        (FakeVerifier(phone="invalid"), FakeRepository(member())),
        (FakeVerifier(), ConflictingRepository()),
    ]
    for verifier, repository in cases:
        with make_client(settings, ready_probes, verifier, repository) as client:
            response = client.post("/v1/auth/member/session", json=payload())
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_FAILED"


def test_verified_new_member_receives_immediate_access_before_profile_completion(
    settings, ready_probes
):
    new_member = member(
        display_name=None,
        preferred_language=None,
        profile_complete=False,
    )
    repository = FakeRepository(new_member)
    with make_client(settings, ready_probes, FakeVerifier(), repository) as client:
        response = client.post("/v1/auth/member/session", json=payload())
    assert response.status_code == 200
    assert response.json()["user"] == {
        "id": str(MEMBER_ID),
        "role": "member",
        "status": "active",
        "displayName": None,
        "preferredLanguage": None,
        "profileComplete": False,
        "createdAt": "2026-09-12T12:00:00Z",
        "updatedAt": "2026-09-12T12:00:00Z",
    }
    assert repository.calls == 1


def test_suspended_deleted_and_wrong_role_accounts_fail_closed(settings, ready_probes):
    expectations = [
        (member(status="suspended"), 403, "ACCOUNT_SUSPENDED"),
        (member(status="deleted"), 401, "AUTHENTICATION_FAILED"),
        (member(role="administrator"), 401, "AUTHENTICATION_FAILED"),
    ]
    for record, status, code in expectations:
        with make_client(settings, ready_probes, FakeVerifier(), FakeRepository(record)) as client:
            response = client.post("/v1/auth/member/session", json=payload())
        assert response.status_code == status
        assert response.json()["code"] == code


def test_unavailable_dependencies_return_retryable_safe_problem(settings, ready_probes):
    cases = [
        (
            FakeVerifier(failure=AuthenticationDependencyUnavailable()),
            FakeRepository(member()),
            FakeIssuer(),
        ),
        (FakeVerifier(), FakeRepository(member(), unavailable=True), FakeIssuer()),
        (FakeVerifier(), FakeRepository(member()), FakeIssuer(unavailable=True)),
    ]
    for verifier, repository, issuer in cases:
        with make_client(settings, ready_probes, verifier, repository, issuer) as client:
            response = client.post("/v1/auth/member/session", json=payload())
        assert response.status_code == 503
        assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
        assert response.json()["retryable"] is True


def test_unwired_handler_and_invalid_payload_fail_safely(settings, ready_probes):
    with TestClient(create_app(settings, ready_probes)) as client:
        unavailable = client.post("/v1/auth/member/session", json=payload())
        invalid = client.post(
            "/v1/auth/member/session",
            json={**payload(), "providerIdToken": "short", "otp": "123456"},
        )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "VALIDATION_FAILED"
    assert PROVIDER_TOKEN not in unavailable.text
