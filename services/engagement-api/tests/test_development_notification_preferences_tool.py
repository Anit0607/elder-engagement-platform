"""Notification-preference development trial guards without network calls."""

from __future__ import annotations

import pytest

from tools import test_development_notification_preferences as trial
from tools.test_development_member_login import SafeTestFailure


def setup_trial(monkeypatch, *, bad_path=None):
    calls = []
    preferences = {
        "eventReminders": True,
        "contentUpdates": False,
        "deliveryWindow": {
            "enabled": False,
            "timeZone": "Asia/Kolkata",
            "startLocalTime": "09:00",
            "endLocalTime": "18:00",
        },
        "updatedAt": "2026-09-15T00:00:00Z",
    }

    def request(method, url, **kwargs):
        path = url.removeprefix("https://synthetic.run.app")
        body = kwargs.get("json")
        calls.append((method, path, body))
        if path == bad_path:
            return 503, {}
        if path == "/v1/auth/member/session":
            return 200, {
                "accessToken": "fixture-access",
                "refreshToken": "fixture-refresh",
                "user": {"id": "fixture-member", "role": "member"},
            }
        if path == "/v1/auth/logout":
            return 204, {}
        if method == "GET":
            return 200, dict(preferences)
        if "unknown" in body:
            return 400, {}
        preferences.clear()
        preferences.update(body, updatedAt="2026-09-15T00:01:00Z")
        return 200, dict(preferences)

    monkeypatch.setattr(trial, "request_json", request)
    return calls


def test_trial_saves_reads_rejects_unknown_restores_and_logs_out(monkeypatch):
    calls = setup_trial(monkeypatch)
    checks = trial.check_notification_preferences(
        "https://synthetic.run.app", "fixture-gateway", "fixture-proof"
    )
    assert checks == [
        "safe_defaults_or_existing_preferences_read",
        "member_choices_saved_and_read_back",
        "unexpected_fields_rejected",
    ]
    assert calls[-2][0:2] == ("PUT", "/v1/me/notification-preferences")
    assert calls[-2][2]["eventReminders"] is True
    assert calls[-2][2]["contentUpdates"] is False
    assert "updatedAt" not in calls[-2][2]
    assert calls[-1] == ("POST", "/v1/auth/logout", None)


@pytest.mark.parametrize(
    "bad_path",
    [
        "/v1/auth/member/session",
        "/v1/me/notification-preferences",
    ],
)
def test_trial_fails_closed_on_unexpected_response(monkeypatch, bad_path):
    calls = setup_trial(monkeypatch, bad_path=bad_path)
    with pytest.raises(SafeTestFailure):
        trial.check_notification_preferences(
            "https://synthetic.run.app", "fixture-gateway", "fixture-proof"
        )
    if bad_path != "/v1/auth/member/session":
        assert calls[-1][0:2] == ("POST", "/v1/auth/logout")


def test_trial_never_prints_tokens(monkeypatch, capsys):
    setup_trial(monkeypatch)
    trial.check_notification_preferences(
        "https://synthetic.run.app", "fixture-gateway", "fixture-proof"
    )
    assert capsys.readouterr().out == ""
