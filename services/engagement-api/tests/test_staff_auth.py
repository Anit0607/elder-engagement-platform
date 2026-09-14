from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.staff_auth import StaffSessionRequest, StaffSessionResponse, StaffUserSummary

PASSWORD = "synthetic-not-a-working-password"  # noqa: S105 - non-working test fixture
CODE = "654321"
INSTALLATION = "22222222-2222-4222-8222-222222222222"
USER = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def payload(**changes):
    return {"username": "synthetic.staff", "password": PASSWORD,
            "installationId": INSTALLATION, "platform": "web", **changes}


class SyntheticHandler:
    """Injected only into tests; no runtime flag/config can enable this fixture."""

    def __init__(self, *, role="contributor", failure=None):
        self.role, self.failure, self.calls = role, failure, 0

    async def create(self, request):
        self.calls += 1
        assert request.password.get_secret_value() == PASSWORD
        if self.failure:
            raise self.failure
        return StaffSessionResponse(
            accessToken="synthetic-access", refreshToken="synthetic-refresh", expiresInSeconds=600,
            user=StaffUserSummary(id=USER, role=self.role, status="active", profileComplete=False,
                                  createdAt=NOW, updatedAt=NOW),
        )


def test_staff_route_is_unavailable_without_real_adapter(settings, ready_probes):
    with TestClient(create_app(settings, ready_probes)) as client:
        response = client.post("/v1/auth/staff/session", json=payload())
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["retryable"] is False
    assert "accessToken" not in response.text


@pytest.mark.parametrize("role", ["contributor", "administrator"])
@pytest.mark.parametrize("platform", ["android", "ios", "web"])
def test_staff_route_matches_shared_client_contract(settings, ready_probes, role, platform):
    handler = SyntheticHandler(role=role)
    with TestClient(create_app(settings, ready_probes, staff_session_handler=handler)) as client:
        response = client.post(
            "/v1/auth/staff/session", json=payload(platform=platform, secondFactorCode=CODE),
        )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == role
    assert response.json()["user"]["id"] == USER
    assert set(response.json()) == {"accessToken", "refreshToken", "expiresInSeconds", "tokenType", "user"}
    assert PASSWORD not in response.text
    assert CODE not in response.text


@pytest.mark.parametrize("changes", [
    {"role": "administrator"}, {"username": "ab"}, {"username": "a" * 121},
    {"password": "short"}, {"password": "a" * 257}, {"password": 123456789012},
    {"secondFactorCode": "12345"}, {"secondFactorCode": "123456789"},
    {"secondFactorCode": "১২৩৪৫৬"}, {"secondFactorCode": 123456},
    {"platform": "unknown"}, {"installationId": "not-a-uuid"}, {"deviceName": "a" * 121},
])
def test_invalid_or_client_role_input_never_reaches_staff_handler(settings, ready_probes, changes):
    handler = SyntheticHandler()
    with TestClient(create_app(settings, ready_probes, staff_session_handler=handler)) as client:
        response = client.post("/v1/auth/staff/session", json=payload(**changes))
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert handler.calls == 0
    assert PASSWORD not in response.text
    assert CODE not in response.text


@pytest.mark.parametrize("status,code", [
    (401, "AUTHENTICATION_FAILED"), (403, "MFA_REQUIRED"),
    (403, "ACCOUNT_SUSPENDED"), (429, "RATE_LIMITED"), (503, "DEPENDENCY_UNAVAILABLE"),
])
def test_staff_failure_uses_existing_safe_problem_contract(settings, ready_probes, status, code):
    handler = SyntheticHandler(
        failure=MemberSessionFailure(status=status, code=code, title="Sign-in refused"),
    )
    with TestClient(create_app(settings, ready_probes, staff_session_handler=handler)) as client:
        response = client.post("/v1/auth/staff/session", json=payload())
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "accessToken" not in response.text
    if status == 429:
        assert response.headers["Retry-After"] == "600"


def test_staff_secrets_are_masked_in_normal_diagnostics():
    request = StaffSessionRequest.model_validate(payload(secondFactorCode=CODE))
    for rendered in [str(request), repr(request), request.model_dump_json()]:
        assert PASSWORD not in rendered
        assert CODE not in rendered
    assert request.second_factor_code.get_secret_value() == CODE


@pytest.mark.parametrize("role,status", [("member", "active"), ("contributor", "invited"),
                                         ("administrator", "suspended"), ("administrator", "deleted")])
def test_staff_response_rejects_member_or_inactive_accounts(role, status):
    with pytest.raises(ValidationError):
        StaffUserSummary(
            id=USER, role=role, status=status, profileComplete=False, createdAt=NOW, updatedAt=NOW,
        )


def test_staff_request_schema_keeps_secrets_write_only():
    fields = StaffSessionRequest.model_json_schema()["properties"]
    assert fields["password"]["writeOnly"] is True
    assert fields["password"]["minLength"] == 12
    assert fields["password"]["maxLength"] == 256
    assert fields["secondFactorCode"]["anyOf"][0]["writeOnly"] is True
