from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from tests.test_development_login_relay import local_server
from tools import development_login_relay as relay

ACCESS = "Bearer " + "a" * 32
REFRESH = "amr1_" + "a" * 64


class Raw:
    def __init__(self, data):
        self.data = data

    def read(self, size, *, decode_content):
        assert decode_content is True
        return self.data[:size]


@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/me/sessions"), ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/refresh"), ("DELETE", f"/v1/me/sessions/{uuid4()}"),
])
def test_session_controls_disabled_unless_explicitly_enabled(method, path):
    with local_server() as origin:
        assert requests.request(method, origin + path, timeout=2).status_code == 404


@pytest.mark.parametrize("method,path,status", [
    ("GET", "/v1/me/sessions", 200), ("POST", "/v1/auth/logout", 204),
    ("POST", "/v1/auth/refresh", 200), ("DELETE", f"/v1/me/sessions/{uuid4()}", 204),
])
def test_opt_in_controls_use_separate_cloud_and_member_credentials(monkeypatch, method, path, status):
    real_request = requests.request
    calls, closed = [], []
    monkeypatch.setattr(relay.LoginRelay, "allow_session_controls", True)
    monkeypatch.setattr(relay.LoginRelay, "origin", "https://synthetic.run.app")
    monkeypatch.setattr(relay, "cloud_cli", lambda *args: "fixture-operator")

    def forward(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=status, raw=Raw(b"{}"), close=lambda: closed.append(True))

    monkeypatch.setattr(relay.requests, "request", forward)
    body = {"refreshToken": REFRESH} if path == "/v1/auth/refresh" else None
    with local_server() as origin:
        result = real_request(method, origin + path, headers={"Authorization": ACCESS}, json=body, timeout=2)
    assert result.status_code == status
    assert result.content == (b"" if status == 204 else b"{}")
    assert "fixture-operator" not in result.text
    assert result.headers["Cache-Control"] == "no-store"
    assert calls[0][:2] == (method, "https://synthetic.run.app" + path)
    options = calls[0][2]
    assert options["headers"]["X-Serverless-Authorization"] == "Bearer fixture-operator"
    assert options["headers"].get("Authorization") == (None if body else ACCESS)
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert options["json"] == body
    assert closed == [True]


@pytest.mark.parametrize("method,path,body,headers,status", [
    ("GET", "/v1/me/sessions", None, {}, 401),
    ("POST", "/v1/auth/logout", {"role": "administrator"}, {"Authorization": ACCESS}, 400),
    ("POST", "/v1/auth/refresh", {}, {}, 400),
    ("POST", "/v1/auth/refresh", {"refreshToken": "short"}, {}, 400),
    ("POST", "/v1/auth/refresh", {"refreshToken": REFRESH, "role": "administrator"}, {}, 400),
    ("DELETE", "/v1/me/sessions/../foreign", None, {"Authorization": ACCESS}, 404),
    ("GET", "/v1/me/sessions?extra=1", None, {"Authorization": ACCESS}, 404),
])
def test_controls_reject_extra_routes_bodies_and_missing_member_credentials(
        monkeypatch, method, path, body, headers, status):
    monkeypatch.setattr(relay.LoginRelay, "allow_session_controls", True)
    with local_server() as origin:
        result = requests.request(method, origin + path, headers=headers, json=body, timeout=2)
    assert result.status_code == status


@pytest.mark.parametrize("status,content", [(302, b"{}"), (200, b"x" * 32_769), (500, b"private")],
                         ids=["redirect", "oversize", "internal"])
def test_controls_hide_redirects_oversize_and_unexpected_private_failures(monkeypatch, status, content):
    real_get = requests.get
    monkeypatch.setattr(relay.LoginRelay, "allow_session_controls", True)
    monkeypatch.setattr(relay, "cloud_cli", lambda *args: "fixture-operator")
    monkeypatch.setattr(relay.requests, "request", lambda *args, **kwargs: SimpleNamespace(
        status_code=status, raw=Raw(content), close=lambda: None))
    with local_server() as origin:
        result = real_get(origin + "/v1/me/sessions", headers={"Authorization": ACCESS}, timeout=2)
    assert result.status_code == 503
    assert result.content == b"{}"
