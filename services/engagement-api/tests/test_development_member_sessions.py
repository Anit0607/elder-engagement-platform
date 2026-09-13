from __future__ import annotations

from uuid import uuid4

import pytest

from tools import test_development_member_sessions as trial
from tools.test_development_member_login import SafeTestFailure


def session(name):
    return {"accessToken": f"fixture-access-{name}", "refreshToken": f"fixture-refresh-{name}",
            "user": {"id": "fixture-member", "role": "member", "status": "active"}}


def responses():
    current_id = str(uuid4())
    first, second, third, renewed = (session(name) for name in ["first", "second", "third", "renewed"])
    return [
        (200, first), (200, second), (200, renewed),
        (401, {"code": "AUTHENTICATION_FAILED"}), (200, []),
        (409, {"code": "REFRESH_TOKEN_REUSED"}), (401, {"code": "SESSION_REVOKED"}), (200, []),
        (204, {}), (401, {"code": "SESSION_REVOKED"}), (200, third),
        (200, [{"id": current_id, "current": True}, {"id": str(uuid4()), "current": False}]),
        (204, {}), (401, {"code": "SESSION_REVOKED"}), (403, {}),
    ]


def test_trial_is_bounded_checks_revocation_and_removes_only_its_new_current_device(monkeypatch, capsys):
    pending = responses()
    current_id = pending[11][1][0]["id"]
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return pending.pop(0)

    monkeypatch.setattr(trial, "request_json", request)
    checks = trial.check_sessions("https://synthetic.run.app", "fixture-operator", "fixture-proof")
    assert len(checks) == 7
    assert not pending
    assert len(calls) == 15
    for _, _, kwargs in calls[:-1]:
        assert kwargs["headers"]["X-Serverless-Authorization"] == "Bearer fixture-operator"
        if kwargs["json"]:
            assert kwargs["json"].get("refreshToken") != "fixture-operator"
    assert calls[2][2]["headers"] == {"X-Serverless-Authorization": "Bearer fixture-operator"}
    assert calls[2][2]["json"] == {"refreshToken": "fixture-refresh-first"}
    deletes = [url for method, url, _ in calls if method == "DELETE"]
    assert deletes == [f"https://synthetic.run.app/v1/me/sessions/{current_id}"]
    assert calls[-1][2] == {}
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("position,replacement", [
    (0, (503, {})), (1, (200, {**session("second"), "user": {"id": "other", "role": "member",
                                                             "status": "active"}})),
    (2, (200, session("first"))), (5, (200, {})), (11, (200, [])), (14, (200, {})),
])
def test_trial_fails_closed_on_unexpected_response(monkeypatch, position, replacement):
    pending = responses()
    pending[position] = replacement
    monkeypatch.setattr(trial, "request_json", lambda *args, **kwargs: pending.pop(0))
    with pytest.raises(SafeTestFailure):
        trial.check_sessions("https://synthetic.run.app", "fixture-operator", "fixture-proof")


def test_fictional_identity_lookup_requests_only_test_and_client_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(trial, "cloud_cli", lambda *args: "fixture-operator")

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return 403, {}

    monkeypatch.setattr(trial, "request_json", request)
    with pytest.raises(SafeTestFailure):
        trial.fictional_proof("synthetic-project")
    assert calls[0][2]["params"] == {"fields": "signIn.phoneNumber.testPhoneNumbers,client.apiKey"}


def test_provider_trial_uses_only_cloud_allowlisted_fictional_identity(monkeypatch):
    pending = [(200, {"signIn": {"phoneNumber": {"testPhoneNumbers": {"+911234567890": "123456"}}},
                       "client": {"apiKey": "fixture-client"}}),
               (200, {"sessionInfo": "fixture-verification"}), (200, {"idToken": "fixture-proof"})]
    calls = []
    monkeypatch.setattr(trial, "cloud_cli", lambda *args: "fixture-operator")

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return pending.pop(0)

    async def verify(project, proof):
        assert (project, proof) == ("synthetic-project", "fixture-proof")

    monkeypatch.setattr(trial, "request_json", request)
    monkeypatch.setattr(trial, "verify_google_proof", verify)
    assert trial.fictional_proof("synthetic-project") == "fixture-proof"
    assert not pending
    assert calls[1][2]["json"] == {"phoneNumber": "+911234567890", "recaptchaToken": "NO_RECAPTCHA"}
    assert calls[2][2]["json"] == {"sessionInfo": "fixture-verification", "code": "123456"}
