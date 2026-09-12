from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import requests

from tools import development_login_relay as relay


@contextmanager
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), relay.LoginRelay)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_relay_accepts_only_the_login_path_and_bounded_android_payload():
    with local_server() as origin:
        assert requests.get(origin + "/health", timeout=2).status_code == 404
        assert requests.post(origin + "/anything", json={}, timeout=2).status_code == 404
        assert requests.post(origin + "/v1/auth/member/session", data=b"x" * 16385,
                             timeout=2).status_code == 413
        assert requests.post(origin + "/v1/auth/member/session", json={"platform": "ios"},
                             timeout=2).status_code == 400


def test_relay_does_not_forward_operator_credentials_to_device(monkeypatch):
    real_post = requests.post
    calls = []

    def cloud_post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, content=b'{"synthetic":"session-response"}')

    monkeypatch.setattr(relay, "cloud_cli", lambda *args: "synthetic-operator-proof")
    monkeypatch.setattr(relay.requests, "post", cloud_post)
    relay.LoginRelay.origin = "https://synthetic.run.app"
    with local_server() as origin:
        result = real_post(origin + "/v1/auth/member/session", json={
            "platform": "android", "providerIdToken": "synthetic-provider-proof",
            "installationId": "synthetic-installation",
        }, timeout=2)
    assert result.status_code == 200
    assert b"operator" not in result.content
    assert "Authorization" not in result.headers
    assert calls[0][1]["headers"]["Authorization"] == "Bearer synthetic-operator-proof"
    assert calls[0][1]["allow_redirects"] is False


def test_relay_hides_private_dependency_errors(monkeypatch):
    def failure(*args):
        raise RuntimeError("synthetic private credential detail")

    monkeypatch.setattr(relay, "cloud_cli", failure)
    with local_server() as origin:
        result = requests.post(origin + "/v1/auth/member/session", json={
            "platform": "android", "providerIdToken": "synthetic-provider-proof",
        }, timeout=2)
    assert result.status_code == 503
    assert b"credential" not in result.content
