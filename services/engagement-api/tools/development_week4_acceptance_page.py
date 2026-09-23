"""Loopback-only Sprint 4 backend acceptance page for fictional accounts.

This is a client-triggered demonstration of the five EE-027 backend journeys,
not the finished Administrator/Contributor console or production acceptance.
The browser never receives passwords, tokens, account identifiers or signed
media links. All fixture data and test output remain on the operator's D drive.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer

from tools.test_development_circles import CircleProof, load_private_inputs
from tools.test_development_content_feed import FeedProof
from tools.test_development_content_moderation import ModerationProof
from tools.test_development_content_uploads import (
    ContentUploadProof,
    private_inputs,
    sample_paths,
)
from tools.test_development_events import EventProof
from tools.test_development_member_login import ROOT, SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof
from tools.test_development_notification_preferences import check_notification_preferences

PAGE_HOST = "127.0.0.1"
PAGE_PORT = 8792
PAGE_ORIGIN = f"http://{PAGE_HOST}:{PAGE_PORT}"
API_ORIGIN = "https://api-test.eldercaresaathi.com"

JOURNEYS = {
    3: "Circles and suggestions",
    4: "Contributor video, audio and PDF uploads",
    5: "Administrator approval and rejection",
    6: "Member feed and circle-only access",
    7: "Events and saved notification preferences",
}


def run_journey(number: int, project: str) -> list[str]:
    """Run existing synthetic proofs through the approved public test address."""
    origin = API_ORIGIN
    gateway = ""  # The load balancer, not a direct Cloud Run URL, protects this route.
    if number == 3:
        inputs = load_private_inputs(ROOT / "secure-runtime" / "fictional-staff-private" / "setup-input.json")
        return CircleProof(origin, gateway, inputs).run(fictional_proof(project, identity_index=1))
    inputs = private_inputs()
    if number == 4:
        samples = sample_paths(ROOT / "output" / "synthetic-media")
        return ContentUploadProof(origin, gateway, inputs).run(samples)
    if number == 5:
        return ModerationProof(origin, gateway, inputs).run()
    if number == 6:
        proofs = [fictional_proof(project, identity_index=index) for index in (0, 1)]
        sample = ROOT / "output" / "synthetic-media" / "amiko-synthetic-upload-sample.mp4"
        return FeedProof(origin, gateway, inputs).run(proofs, sample)
    if number == 7:
        proofs = [fictional_proof(project, identity_index=index) for index in (0, 1)]
        event_checks = EventProof(origin, gateway, inputs).run(proofs)
        preference_checks = check_notification_preferences(
            origin, gateway, fictional_proof(project, identity_index=1)
        )
        return event_checks + preference_checks
    raise SafeTestFailure("Unknown acceptance journey")


class AcceptancePage(BaseHTTPRequestHandler):
    project = ""
    csrf = ""
    cached_results: dict[int, list[str]] = {}

    def log_message(self, _format, *_args):
        pass

    def local_request(self) -> bool:
        return self.client_address[0] == PAGE_HOST and self.headers.get("Host") == f"{PAGE_HOST}:{PAGE_PORT}"

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if not self.local_request() or self.path != "/":
            self.reply(404, b"{}", "application/json")
            return
        cards = "".join(
            f'<section class="card"><h2>{number}. {title}</h2>'
            f'<p id="result-{number}">Ready to check with fictional accounts.</p>'
            f'<button data-journey="{number}">Run this check</button></section>'
            for number, title in JOURNEYS.items()
        )
        page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amiko Sprint 4 client review</title>
<style>
body{{font:18px system-ui;max-width:850px;margin:28px auto;padding:18px;background:#f4f7fb;color:#122b45}}
h1{{font-size:30px}} h2{{font-size:20px}} p{{line-height:1.5}}
.card{{background:white;border-radius:13px;padding:22px;margin:15px 0;box-shadow:0 3px 16px #17324d18}}
button{{font:inherit;font-weight:650;padding:12px 18px;border:0;border-radius:8px;
background:#1769aa;color:white}}
button:disabled{{opacity:.55}} [id^=result-]{{white-space:pre-wrap}}
</style>
<h1>Amiko — Sprint 4 backend review</h1>
<p>This local page checks the five EE-027 backend journeys against the protected
development address. It uses fictional people and generated files only. It does
not send a real text message, publish client content or test the future Android,
Administrator or Contributor screens. The Week 2 login/profile journeys were
accepted earlier.</p>
<p>Click each check once and review the result. A green technical result does not
automatically mean client acceptance: please report any business mismatch to
Codex, then confirm the five results with the client.</p>
{cards}
<script nonce="{self.csrf}">
for(const button of document.querySelectorAll('button[data-journey]')){{
 button.addEventListener('click',async()=>{{
  const n=Number(button.dataset.journey), box=document.getElementById('result-'+n);
  button.disabled=true; box.textContent='Checking the protected test system…';
  try{{
   const response=await fetch('/run',{{method:'POST',headers:{{'Content-Type':'application/json',
     'X-CSRF-Token':'{self.csrf}'}},body:JSON.stringify({{journey:n}})}});
   const result=await response.json();
   if(!response.ok) throw new Error(result.message||'The check did not complete');
   box.textContent='TECHNICAL CHECK PASSED\\n'+result.checks.map((c,i)=>
     (i+1)+'. '+c.replaceAll('_',' ')).join('\\n');
  }}catch(error){{box.textContent='NOT COMPLETED — '+error.message+
    '\\nPlease tell Codex the journey number and this message.'}}
  finally{{button.disabled=false}}
 }});
}}
</script></html>"""
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            f"script-src 'nonce-{self.csrf}'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_POST(self):
        if (
            not self.local_request()
            or self.path != "/run"
            or self.headers.get("Origin") not in {None, PAGE_ORIGIN}
            or self.headers.get("X-CSRF-Token") != self.csrf
            or self.headers.get("Content-Type") != "application/json"
        ):
            self.reply(403, b'{"message":"Request rejected"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 1 <= length <= 32:
            self.reply(400, b'{"message":"Invalid test request"}', "application/json")
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            payload = None
        number = payload.get("journey") if isinstance(payload, dict) else None
        if type(number) is not int or number not in JOURNEYS or payload != {"journey": number}:
            self.reply(400, b'{"message":"Invalid test request"}', "application/json")
            return
        try:
            checks = type(self).cached_results.get(number)
            if checks is None:
                checks = run_journey(number, self.project)
                type(self).cached_results[number] = checks
            self.reply(200, json.dumps({"checks": checks}).encode(), "application/json")
        except SafeTestFailure as error:
            message = str(error)
            if "returned 429" in message:
                message = (
                    "The safety limit for repeated fictional sign-ins is active. "
                    "Please tell Codex; do not keep retrying."
                )
            self.reply(503, json.dumps({"message": message}).encode(), "application/json")
        except Exception:
            self.reply(
                503,
                b'{"message":"Private failure details were suppressed; ask Codex to investigate"}',
                "application/json",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm", required=True, choices=["CLIENT-TEST-EE-027-development"])
    args = parser.parse_args()
    if args.project != "amiko-508302" or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project):
        parser.error("unexpected development project")
    try:
        cloud_cli("auth", "print-access-token")
        status, _ = request_json("GET", API_ORIGIN + "/ready")
        if status != 200:
            raise SafeTestFailure("The protected development service is not ready")
    except SafeTestFailure as error:
        print(f"Acceptance page did not start: {error}")
        return 1
    AcceptancePage.project = args.project
    AcceptancePage.csrf = secrets.token_urlsafe(32)
    server = HTTPServer((PAGE_HOST, PAGE_PORT), AcceptancePage)
    print(f"Sprint 4 acceptance page ready at {PAGE_ORIGIN}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
