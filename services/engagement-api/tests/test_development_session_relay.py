from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from tests.test_development_login_relay import local_server
from tools import development_login_relay as relay

ACCESS = "Bearer " + "a" * 32
REFRESH = "amr1_" + "a" * 64


@pytest.mark.parametrize("length", [-1, 0, 1, 25, 16_384, 16_385, 32_768, 32_769])
def test_rejected_body_drain_covers_small_bodies_but_stays_bounded(length):
    handler = object.__new__(relay.LoginRelay)
    timeouts = []
    handler.connection = SimpleNamespace(settimeout=lambda value: timeouts.append(value))
    handler.rfile = BytesIO(b"x" * max(0, length))
    handler.reject_body(length)
    bounded = 0 < length <= handler.max_body * 2
    assert handler.rfile.tell() == (length if bounded else 0)
    assert timeouts == ([2] if bounded else [])


def test_reply_does_not_read_an_already_consumed_request_body():
    handler = object.__new__(relay.LoginRelay)
    handler.headers = {"Content-Length": "25"}
    handler._body_consumed = True
    handler.rfile = BytesIO(b"unexpected-second-read")
    handler.wfile = BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.reply(400)
    assert handler.rfile.tell() == 0
    assert handler.wfile.getvalue() == b"{}"


def test_partial_rejected_body_is_not_retried_after_timeout():
    handler = object.__new__(relay.LoginRelay)
    handler.connection = SimpleNamespace(settimeout=lambda value: None)
    calls = []

    def timed_out_read(length):
        calls.append(length)
        raise TimeoutError()

    handler.rfile = SimpleNamespace(read=timed_out_read)
    handler.reject_body(25)
    assert calls == [25]
    assert handler._body_consumed is True


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
