"""Loopback-only Android test relay; never exports the operator's cloud token."""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import requests

from tools.test_development_member_login import cloud_cli


class LoginRelay(BaseHTTPRequestHandler):
    server_version = "AmikoDevelopmentRelay"
    origin = ""
    max_body = 16_384
    allow_session_controls = False

    def log_message(self, format, *args):
        pass  # No requests, bodies, identity tokens or personal data in console logs.

    def reply(self, status, body=b"{}"):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.allow_session_controls and self.path in {"/v1/auth/refresh", "/v1/auth/logout"}:
            self.control("POST")
            return
        if self.path != "/v1/auth/member/session" or self.client_address[0] != "127.0.0.1":
            self.reply(404)
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                self.reply(400)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= self.max_body:
                self.reject_body(length)
                self.reply(413)
                return
            self.connection.settimeout(30)
            body = self.rfile.read(length)
            payload = json.loads(body)
            if (
                not isinstance(payload, dict)
                or set(payload) - {"providerIdToken", "installationId", "platform", "deviceName"}
                or payload.get("platform") != "android"
                or not isinstance(payload.get("providerIdToken"), str)
                or len(payload["providerIdToken"]) > 8192
            ):
                self.reply(400)
                return
            token = cloud_cli("auth", "print-identity-token")
            response = requests.post(
                f"{self.origin}/v1/auth/member/session", json=payload,
                headers={"Authorization": f"Bearer {token}"}, timeout=30, allow_redirects=False,
            )
            if response.status_code not in {200, 400, 401, 403, 429, 503}:
                self.reply(503)
            elif len(response.content) > 32_768:
                self.reply(503)
            else:
                self.reply(response.status_code, response.content)
        except Exception:
            self.reply(503)

    def do_GET(self):
        if self.allow_session_controls and self.path == "/v1/me/sessions":
            self.control("GET")
        else:
            self.reply(404)

    def do_DELETE(self):
        if not self.allow_session_controls or not self.path.startswith("/v1/me/sessions/"):
            self.reply(404)
            return
        try:
            device = self.path.removeprefix("/v1/me/sessions/")
            if str(UUID(device)) != device:
                raise ValueError()
        except ValueError:
            self.reply(404)
            return
        self.control("DELETE")

    def control(self, method):
        if self.client_address[0] != "127.0.0.1":
            self.reply(404)
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                self.reply(400)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = None
            headers = {}
            if self.path == "/v1/auth/refresh":
                if not 1 <= length <= self.max_body:
                    self.reject_body(length)
                    self.reply(413)
                    return
                self.connection.settimeout(30)
                payload = json.loads(self.rfile.read(length))
                if (not isinstance(payload, dict) or set(payload) != {"refreshToken"}
                        or not isinstance(payload["refreshToken"], str)
                        or not re.fullmatch(r"amr1_[A-Za-z0-9_-]{64}", payload["refreshToken"])):
                    self.reply(400)
                    return
            else:
                if length != 0:
                    self.reply(400)
                    return
                access = self.headers.get("Authorization", "")
                if not re.fullmatch(r"Bearer [A-Za-z0-9_.-]{32,8192}", access):
                    self.reply(401)
                    return
                headers["Authorization"] = access
            token = cloud_cli("auth", "print-identity-token")
            headers["X-Serverless-Authorization"] = f"Bearer {token}"
            response = requests.request(
                method, self.origin + self.path, json=payload, headers=headers,
                timeout=30, allow_redirects=False, stream=True,
            )
            try:
                content = response.raw.read(32_769, decode_content=True)
                if response.status_code not in {200, 204, 400, 401, 403, 404, 409, 429, 503}:
                    self.reply(503)
                elif len(content) > 32_768:
                    self.reply(503)
                else:
                    self.reply(response.status_code, b"" if response.status_code == 204 else content)
            finally:
                response.close()
        except Exception:
            self.reply(503)

    def reject_body(self, length):
        # Drain only a bounded near-limit body so Windows can receive the rejection
        # instead of resetting the socket with unread bytes. Never forward it.
        if self.max_body < length <= self.max_body * 2:
            self.connection.settimeout(2)
            self.rfile.read(length)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True,
                        choices=["TEST-EE-009-development", "TEST-EE-011-development"])
    parser.add_argument("--session-controls", action="store_true")
    arguments = parser.parse_args()
    if arguments.session_controls != (arguments.confirm == "TEST-EE-011-development"):
        parser.error("session controls require explicit EE-011 development confirmation")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project):
        parser.error("invalid project")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", arguments.region):
        parser.error("invalid region")
    origin = cloud_cli(
        "run", "services", "describe", "ee-development-api", f"--project={arguments.project}",
        f"--region={arguments.region}", "--format=value(status.url)",
    )
    if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
        parser.error("unexpected development service origin")
    LoginRelay.origin = origin
    LoginRelay.allow_session_controls = arguments.session_controls
    server = ThreadingHTTPServer(("127.0.0.1", 8787), LoginRelay)
    print("Development-only login relay listening on 127.0.0.1:8787; no tokens are displayed.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
