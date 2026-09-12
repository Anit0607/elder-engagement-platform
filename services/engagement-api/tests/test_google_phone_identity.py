from __future__ import annotations

from copy import deepcopy

import pytest
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request

from app.google_phone_identity import BoundedCertificateRequest, GooglePhoneIdentityVerifier
from app.member_auth import AuthenticationDependencyUnavailable, IdentityTokenRejected

PROJECT_ID = "synthetic-development-project"
PROVIDER_PROOF = "synthetic-provider-proof"
NOW = 1_800_000_000


def valid_claims() -> dict:
    return {
        "iss": f"https://securetoken.google.com/{PROJECT_ID}",
        "aud": PROJECT_ID,
        "sub": "synthetic-provider-subject",
        "phone_number": "+919999999901",
        "auth_time": NOW - 60,
        "firebase": {"sign_in_provider": "phone"},
    }


class StubTokenVerifier:
    def __init__(self, result=None, failure: Exception | None = None):
        self.result = result
        self.failure = failure
        self.calls = []

    def __call__(self, token, request, *, audience, clock_skew_in_seconds):
        self.calls.append((token, request, audience, clock_skew_in_seconds))
        if self.failure:
            raise self.failure
        return self.result


def adapter(stub: StubTokenVerifier) -> GooglePhoneIdentityVerifier:
    return GooglePhoneIdentityVerifier(
        PROJECT_ID,
        PROJECT_ID,
        verify_token=stub,
        request=object(),
        now=lambda: NOW,
    )


@pytest.mark.anyio
async def test_valid_google_phone_token_returns_verified_identity():
    stub = StubTokenVerifier(valid_claims())
    identity = await adapter(stub).verify(PROVIDER_PROOF)
    assert identity.phone_e164 == "+919999999901"
    assert identity.provider_subject == "synthetic-provider-subject"
    assert stub.calls == [(PROVIDER_PROOF, stub.calls[0][1], PROJECT_ID, 30)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iss", "https://securetoken.google.com/wrong-project"),
        ("aud", "wrong-project"),
        ("sub", ""),
        ("phone_number", "not-a-phone"),
        ("auth_time", 0),
        ("auth_time", True),
        ("auth_time", NOW + 31),
        ("firebase", {"sign_in_provider": "password"}),
    ],
)
async def test_wrong_project_or_non_phone_claims_are_rejected(field, value):
    claims = deepcopy(valid_claims())
    claims[field] = value
    with pytest.raises(IdentityTokenRejected):
        await adapter(StubTokenVerifier(claims)).verify(PROVIDER_PROOF)


@pytest.mark.anyio
async def test_bad_signature_or_expired_token_is_rejected():
    with pytest.raises(IdentityTokenRejected):
        await adapter(StubTokenVerifier(failure=ValueError("invalid token"))).verify(
            PROVIDER_PROOF
        )


@pytest.mark.anyio
async def test_unexpected_provider_response_is_rejected():
    with pytest.raises(IdentityTokenRejected):
        await adapter(StubTokenVerifier([])).verify(PROVIDER_PROOF)


@pytest.mark.anyio
async def test_google_certificate_network_failure_is_retryable():
    failure = google_auth_exceptions.TransportError("temporary network failure")
    with pytest.raises(AuthenticationDependencyUnavailable):
        await adapter(StubTokenVerifier(failure=failure)).verify(PROVIDER_PROOF)


def test_project_and_audience_must_match():
    with pytest.raises(ValueError, match="audience"):
        GooglePhoneIdentityVerifier(PROJECT_ID, "different-project")


def test_certificate_requests_have_a_short_network_timeout(monkeypatch):
    observed = {}

    def fake_request(self, *args, **kwargs):
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(Request, "__call__", fake_request)
    BoundedCertificateRequest()("https://synthetic.example", timeout=120)
    assert observed["timeout"] == 5
