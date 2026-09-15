"""Local-only fictional staff acceptance page. Not an app/admin console.

Cloud tokens, fixture passwords and app session tokens stay on this computer.
The browser shows only test status, role and language; enter changing codes here,
never in chat. Loopback/Host/Origin/CSRF restrictions prevent cross-site requests.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_member_login import ROOT, SafeTestFailure, cloud_cli, request_json

PAGE_ORIGIN = "http://127.0.0.1:8788"


class StaffTrial:
    def __init__(self, origin, inputs):
        self.origin, self.inputs, self.session = origin, inputs, None
        self.installation = str(uuid4())

    def call(self, method, path, body=None):
        headers = {"X-Serverless-Authorization": "Bearer " + cloud_cli("auth", "print-identity-token")}
        if self.session:
            headers["Authorization"] = "Bearer " + self.session["accessToken"]
        return request_json(method, self.origin + path, headers=headers, json=body)

    def verify_account_controls(self):
        if not self.session or self.session.get("user", {}).get("role") != "administrator":
            return 403, {"message": "Sign in as the fictional Administrator first"}
        administrator_id = self.session["user"]["id"]
        contributor = StaffTrial(self.origin, self.inputs)
        status, _ = contributor.perform({"action": "login", "role": "contributor"})
        if status != 200:
            return 503, {"message": "Fictional Contributor preparation did not complete"}
        contributor_id = contributor.session["user"]["id"]
        suspended = False
        checks = []
        try:
            status, result = self.call(
                "PATCH",
                f"/v1/admin/users/{contributor_id}/status",
                {"status": "suspended", "reason": "Client Week 2 fictional verification"},
            )
            if status != 200 or result.get("status") != "suspended":
                return 503, {"message": "Contributor suspension was not confirmed"}
            suspended = True
            status, _ = contributor.call("GET", "/v1/me/profile")
            if status != 403:
                return 503, {"message": "Suspended Contributor access was not blocked"}
            checks.append("suspension")

        finally:
            if suspended:
                status, result = self.call(
                    "PATCH",
                    f"/v1/admin/users/{contributor_id}/status",
                    {"status": "active", "reason": "Restore fictional account after client test"},
                )
                if status != 200 or result.get("status") != "active":
                    raise SafeTestFailure("Fictional Contributor safety restoration was not confirmed")

        restored = StaffTrial(self.origin, self.inputs)
        status, _ = restored.perform({"action": "login", "role": "contributor"})
        if status != 200:
            return 503, {"message": "Restored Contributor sign-in was not confirmed"}
        status, _ = restored.call(
            "PATCH",
            f"/v1/admin/users/{administrator_id}/status",
            {"status": "suspended", "reason": "Expected client permission-denial test"},
        )
        restored.perform({"action": "logout"})
        if status != 403:
            return 503, {"message": "Contributor permission protection was not confirmed"}
        checks.append("permission protection")
        status, _ = self.call(
            "PATCH",
            f"/v1/admin/users/{administrator_id}/status",
            {"status": "suspended", "reason": "Expected last-Administrator protection test"},
        )
        if status != 409:
            return 503, {"message": "Last-Administrator protection was not confirmed"}
        checks.append("Administrator protection")
        return 200, {
            "message": "Account-control test succeeded; fictional Contributor restored to active",
            "role": "administrator",
            "language": self.session["user"].get("preferredLanguage"),
            "checks": len(checks),
        }

    def perform(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"action", "role", "code"}:
            return 400, {"message": "Invalid test request"}
        action = payload.get("action")
        if action == "verify-controls":
            return self.verify_account_controls()
        if action == "login":
            role, code = payload.get("role"), payload.get("code", "")
            if role not in {"administrator", "contributor"} or not isinstance(code, str):
                return 400, {"message": "Choose Administrator or Contributor"}
            if code and not re.fullmatch(r"[0-9]{6}", code):
                return 400, {"message": "Enter a six-digit authenticator code, or leave it empty"}
            if self.session:
                status, _ = self.call("POST", "/v1/auth/logout")
                if status != 204:
                    return 503, {"message": "Previous test sign-out was not confirmed. Retry sign-out first"}
                self.session = None
            password = (
                self.inputs.administrator_password
                if role == "administrator"
                else self.inputs.contributor_password
            ).get_secret_value()
            body = dict(
                username="fictional.ee010." + role,
                password=password,
                installationId=self.installation,
                platform="web",
            )
            if role == "administrator" and code:
                body["secondFactorCode"] = code
            status, response = self.call("POST", "/v1/auth/staff/session", body)
            if status == 200:
                if (
                    response.get("user", {}).get("role") != role
                    or not response.get("accessToken")
                    or not response.get("refreshToken")
                ):
                    return 503, {"message": "Staff response could not be verified"}
                self.session = response
        elif action in {"refresh", "logout", "check"}:
            if not self.session:
                return 400, {"message": "Sign in to the fictional account first"}
            if action == "refresh":
                try:
                    status, response = self.call(
                        "POST", "/v1/auth/refresh", {"refreshToken": self.session["refreshToken"]}
                    )
                except SafeTestFailure:
                    self.session = None
                    return 503, {
                        "message": "Saved login was not confirmed. Sign in again; do not retry renewal"
                    }
                if status == 200:
                    if (
                        response.get("user", {}).get("id") != self.session["user"]["id"]
                        or response.get("user", {}).get("role") != self.session["user"]["role"]
                        or not response.get("accessToken")
                        or not response.get("refreshToken")
                    ):
                        self.session = None
                        return 503, {"message": "Saved-login response could not be verified; sign in again"}
                    self.session = response
                else:
                    self.session = None
                    return status, {
                        "message": "Saved login was not confirmed. Sign in again; do not retry renewal"
                    }
            elif action == "logout":
                status, response = self.call("POST", "/v1/auth/logout")
                if status == 204:
                    self.session = None
            else:
                status, response = self.call("GET", "/v1/me/profile")
        else:
            return 400, {"message": "Unknown test action"}
        if status in {200, 204}:
            user = self.session["user"] if self.session else {}
            return 200, {
                "message": "Signed out successfully" if action == "logout" else "Test succeeded",
                "role": user.get("role"),
                "language": user.get("preferredLanguage"),
            }
        messages = {
            401: "Sign-in rejected. Check the code; use a new changing code if the previous one was used",
            403: "Permission denied or authenticator code required",
            429: "Too many attempts. Wait before trying again",
            503: "Cannot connect to the development service",
        }
        return status if status in messages else 503, {
            "message": messages.get(status, "Test did not complete")
        }


class TrialPage(BaseHTTPRequestHandler):
    trial = None
    csrf = ""

    def log_message(self, format, *args):
        pass

    def reply(self, status, body, *, html=False):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            + "script-src 'nonce-"
            + self.csrf
            + "'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def local(self):
        return self.client_address[0] == "127.0.0.1" and self.headers.get("Host") == "127.0.0.1:8788"

    def do_GET(self):
        if not self.local() or self.path != "/":
            self.reply(404, b"{}")
            return
        page = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Amiko fictional staff test</title>
<style>
body{font:20px system-ui;max-width:780px;margin:40px auto;padding:20px;background:#f3f6fb;color:#142a43}
button,input,select{font:inherit;padding:12px;margin:8px}
pre{white-space:pre-wrap;background:white;padding:20px}
</style>
<h1>Amiko fictional staff test</h1>
<p>This is a local test page, not the final Administrator console. No real member account is used.</p>
<label>Account <select id="role"><option value="administrator">Administrator</option>
<option value="contributor">Contributor</option></select></label>
<p>For Administrator: enter the current six-digit code from your authenticator app.
For Contributor: leave it empty.</p>
<input id="code" inputmode="numeric" maxlength="6" autocomplete="off" placeholder="Changing code">
<button data-action="login">Sign in</button><button data-action="check">Check profile access</button>
<button data-action="refresh">Check saved login</button><button data-action="logout">Sign out</button>
<button data-action="verify-controls">Verify Administrator account controls</button>
<pre id="result">Ready for your test.</pre>
<p>Do not share passwords, setup keys or changing codes in chat or screenshots.</p>
<script nonce="__CSRF__">
const csrf="__CSRF__";
for(const button of document.querySelectorAll('button')) button.onclick=async()=>{
  for(const b of document.querySelectorAll('button')) b.disabled=true;
  try{
    const payload={action:button.dataset.action,role:document.querySelector('#role').value,
      code:document.querySelector('#code').value};
    document.querySelector('#code').value='';
    document.querySelector('#result').textContent='Checking…';
    const response=await fetch('/test',{method:'POST',
      headers:{'Content-Type':'application/json','X-Amiko-Trial':csrf},body:JSON.stringify(payload)});
    const result=await response.json();
    document.querySelector('#result').textContent=[result.message,result.role?'Account: '+result.role:'',
      result.language?'Language: '+result.language:''].filter(Boolean).join('\\n');
  }catch{
    document.querySelector('#result').textContent='Cannot connect. Ask Codex to check the local test page.';
  }finally{
    for(const b of document.querySelectorAll('button')) b.disabled=false;
  }
};
</script></html>"""
        self.reply(200, page.replace("__CSRF__", self.csrf).encode(), html=True)

    def do_POST(self):
        if (
            not self.local()
            or self.path != "/test"
            or self.headers.get("Origin") != PAGE_ORIGIN
            or self.headers.get("X-Amiko-Trial") != self.csrf
        ):
            self.reply(403, b"{}")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 1 <= length <= 2048
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                self.reply(400, b"{}")
                return
            self.connection.settimeout(5)
            status, response = self.trial.perform(json.loads(self.rfile.read(length)))
        except Exception:
            status, response = 503, {"message": "Test stopped. Private details are hidden"}
        self.reply(status, json.dumps(response).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-010-FICTIONAL-development"])
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project) or not re.fullmatch(
        r"[a-z]+-[a-z]+[0-9]+", args.region
    ):
        parser.error("invalid development project or region")
    if ROOT.drive.upper() != "D:":
        raise SafeTestFailure("Private project files must remain on D")
    private = Path(ROOT / "secure-runtime" / "fictional-staff-private" / "setup-input.json")
    inputs = FictionalSetupInput.model_validate_json(private.read_bytes())
    origin = cloud_cli(
        "run",
        "services",
        "describe",
        "ee-development-api",
        f"--project={args.project}",
        f"--region={args.region}",
        "--format=value(status.url)",
    )
    if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
        raise SafeTestFailure("Unexpected development origin")
    TrialPage.trial, TrialPage.csrf = StaffTrial(origin, inputs), secrets.token_urlsafe(32)
    server = HTTPServer(("127.0.0.1", 8788), TrialPage)
    print("Local fictional staff test available at " + PAGE_ORIGIN + "; no credentials printed", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
