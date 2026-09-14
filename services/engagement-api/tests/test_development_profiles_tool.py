"""Profile trial guards without network calls or real identities."""
import pytest

from tools import test_development_profiles as trial
from tools.test_development_member_login import SafeTestFailure, select_fictional_identity


@pytest.mark.parametrize("index", [-1, 2, True, "1"])
def test_identity_index_rejects_invalid_selection(index):
    config = {"signIn": {"phoneNumber": {"testPhoneNumbers": {
        "+911234567890": "123456", "+911234567891": "654321",
    }}}}
    with pytest.raises(SafeTestFailure):
        select_fictional_identity(config, identity_index=index)


def test_second_identity_is_selected_deterministically():
    config = {"signIn": {"phoneNumber": {"testPhoneNumbers": {
        "+911234567891": "654321", "+911234567890": "123456",
    }}}}
    assert select_fictional_identity(config, identity_index=1) == ("+911234567891", "654321")


def setup_trial(monkeypatch, *, existing=None, bad_path=None):
    calls = []
    profile = dict(existing or {})

    def request(method, url, **kwargs):
        path = url.removeprefix("https://synthetic.run.app")
        body = kwargs.get("json")
        calls.append((method, path, body))
        if path == "/v1/auth/member/session":
            return 200, {"accessToken": "fixture-access", "refreshToken": "fixture-refresh",
                         "user": {"id": "fixture-member", "role": "member"}}
        if path == "/v1/auth/logout":
            return 204, {}
        if path == bad_path:
            return 503, {}
        if path == "/v1/auth/refresh":
            return 200, {"accessToken": "fixture-renewed", "user": {
                "id": "fixture-member", "preferredLanguage": "en", "profileComplete": True,
            }}
        if method == "GET":
            return (200, dict(profile)) if profile else (404, {})
        if body.get("preferredLanguage") == "fr" or "role" in body:
            return 400, {}
        profile.update(body)
        profile.update(id="fixture-member", role="member", status="active")
        return 200, dict(profile)

    monkeypatch.setattr(trial, "request_json", request)
    return calls


def test_successful_trial_retains_fixture_and_logs_out(monkeypatch):
    calls = setup_trial(monkeypatch)
    checks = trial.check_profiles("https://synthetic.run.app", "fixture-gateway", "fixture-proof")
    assert len(checks) == 5
    assert calls[-1] == ("POST", "/v1/auth/logout", None)
    assert not any(method == "DELETE" for method, _, _ in calls)


def test_non_fixture_profile_is_never_overwritten(monkeypatch):
    calls = setup_trial(monkeypatch, existing={"displayName": "Existing profile"})
    with pytest.raises(SafeTestFailure, match="Will not overwrite"):
        trial.check_profiles("https://synthetic.run.app", "fixture-gateway", "fixture-proof")
    assert not any(method == "PATCH" for method, _, _ in calls)
    assert calls[-1][1] == "/v1/auth/logout"


def test_failure_still_logs_out_trial_session(monkeypatch):
    calls = setup_trial(monkeypatch, bad_path="/v1/auth/refresh")
    with pytest.raises(SafeTestFailure):
        trial.check_profiles("https://synthetic.run.app", "fixture-gateway", "fixture-proof")
    assert calls[-1][1] == "/v1/auth/logout"
