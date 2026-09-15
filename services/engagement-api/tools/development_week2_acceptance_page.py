"""Loopback-only Week 2 client acceptance page for profiles and photos.

The page uses only configured fictional phone identities and an in-memory
synthetic image. It never sends a real SMS or returns credentials, tokens,
identifiers, phone numbers, signed URLs or cloud failure details to the browser.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer

from tools.test_development_member_login import SafeTestFailure, cloud_cli
from tools.test_development_member_sessions import fictional_proof
from tools.test_development_profile_photos import check_profile_photo
from tools.test_development_profiles import check_profiles

PAGE_HOST = "127.0.0.1"
PAGE_PORT = 8790
PAGE_ORIGIN = f"http://{PAGE_HOST}:{PAGE_PORT}"

FRIENDLY_CHECKS = {
    "approved_profile_fields_saved_for_same_member": "Approved profile details save correctly",
    "english_bengali_hindi_saved_and_omitted_fields_preserved": (
        "English, Bengali and Hindi save without losing other profile details"
    ),
    "unsupported_language_and_self_assigned_permissions_rejected": (
        "Invalid language and self-promotion to Administrator are blocked"
    ),
    "age_label_is_not_an_access_restriction": "The 55+ label does not block younger users",
    "renewed_login_reads_saved_english_profile": "A renewed login sees the saved profile",
    "short_lived_restricted_upload_authorised": "Photo upload permission is short-lived and restricted",
    "synthetic_photo_uploaded_directly_to_private_storage": (
        "The synthetic photo reaches private storage without passing through the app server"
    ),
    "photo_converted_to_metadata_free_webp": (
        "The photo is cleaned, converted and stripped of hidden source information"
    ),
    "profile_read_succeeded_and_completed_upload_reuse_was_rejected": (
        "The profile can show the photo and a completed upload cannot be reused"
    ),
}


def run_acceptance(project: str, region: str) -> dict:
    origin = cloud_cli(
        "run",
        "services",
        "describe",
        "ee-development-api",
        f"--project={project}",
        f"--region={region}",
        "--format=value(status.url)",
    )
    if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
        raise SafeTestFailure("The development service address could not be verified")
    gateway = cloud_cli("auth", "print-identity-token")
    profile_checks = check_profiles(origin, gateway, fictional_proof(project, identity_index=1))
    photo_checks = check_profile_photo(origin, gateway, fictional_proof(project, identity_index=1))
    checks = profile_checks + photo_checks
    if set(checks) != set(FRIENDLY_CHECKS):
        raise SafeTestFailure("The expected Week 2 checks did not all complete")
    return {
        "status": "passed",
        "message": "All remaining Week 2 profile and photo checks succeeded",
        "checks": [FRIENDLY_CHECKS[item] for item in checks],
        "realSmsSent": False,
        "personalPhotoUsed": False,
    }


class AcceptancePage(BaseHTTPRequestHandler):
    project = ""
    region = ""
    csrf = ""

    def log_message(self, _format, *_args):
        pass

    def local_request(self) -> bool:
        return self.client_address[0] == PAGE_HOST and self.headers.get("Host") == f"{PAGE_HOST}:{PAGE_PORT}"

    def reply(self, status: int, body: bytes, *, content_type: str) -> None:
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
            self.reply(404, b"{}", content_type="application/json")
            return
        page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amiko Week 2 acceptance</title>
<style>
body{{font:18px system-ui;max-width:820px;margin:32px auto;padding:20px;background:#f4f7fb;color:#122b45}}
.card{{background:white;border-radius:14px;padding:24px;margin:16px 0;box-shadow:0 3px 16px #17324d18}}
h1{{font-size:30px}} h2{{font-size:21px}} li{{margin:9px 0}}
button{{font:inherit;font-weight:650;padding:14px 20px;border:0;border-radius:9px;
background:#1769aa;color:white}}
button:disabled{{opacity:.55}} #result{{white-space:pre-wrap;line-height:1.5}}
</style>
<h1>Amiko — Week 2 client acceptance</h1>
<div class="card"><h2>Already confirmed in earlier client tests</h2><ul>
<li>Member phone sign-in and real text-message sign-in</li>
<li>Saved login, logout and secure session renewal</li>
<li>Contributor password sign-in</li>
<li>Administrator password plus authenticator-app sign-in</li>
<li>English, Bengali and Hindi screen preference</li>
<li>Administrator suspension/reactivation and permission protection</li>
</ul></div>
<div class="card"><h2>Remaining acceptance check</h2>
<p>This uses a fictional Member and a generated picture. It sends no real text
message and uses no personal photo.</p>
<button id="run">Run profile and photo checks</button>
<p id="result">Ready. The check normally takes under one minute.</p></div>
<script nonce="{self.csrf}">
const button=document.getElementById('run'), result=document.getElementById('result');
button.onclick=async()=>{{
 button.disabled=true; result.textContent='Checking the private development system…';
 try{{
  const response=await fetch('/run',{{
   method:'POST',
   headers:{{'Content-Type':'application/json','X-CSRF-Token':'{self.csrf}'}},
   body:'{{"action":"run"}}'
  }});
  const data=await response.json();
  if(!response.ok) throw new Error(data.message||'The check did not complete');
  result.textContent='SUCCESS\\n\\n'
   +data.checks.map((x,i)=>(i+1)+'. '+x).join('\\n')
   +'\\n\\nNo real text message or personal photo was used.';
 }}catch(error){{
  result.textContent='NOT COMPLETED\\n\\n'+error.message
   +'\\nPlease tell Codex exactly what this box says.'
 }}
 finally{{button.disabled=false}}
}};
</script></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page.encode())))
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
        self.wfile.write(page.encode())
        self.close_connection = True

    def do_POST(self):
        if (
            not self.local_request()
            or self.path != "/run"
            or self.headers.get("Origin") not in {None, PAGE_ORIGIN}
            or self.headers.get("X-CSRF-Token") != self.csrf
            or self.headers.get("Content-Type") != "application/json"
        ):
            self.reply(403, b'{"message":"Request rejected"}', content_type="application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > 64:
            self.reply(400, b'{"message":"Invalid test request"}', content_type="application/json")
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if payload != {"action": "run"}:
            self.reply(400, b'{"message":"Invalid test request"}', content_type="application/json")
            return
        try:
            result = run_acceptance(self.project, self.region)
            body = json.dumps(result).encode()
            self.reply(200, body, content_type="application/json")
        except SafeTestFailure as error:
            body = json.dumps({"message": str(error)}).encode()
            self.reply(503, body, content_type="application/json")
        except Exception:
            self.reply(
                503,
                b'{"message":"Private failure details were suppressed; ask Codex to investigate"}',
                content_type="application/json",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["CLIENT-TEST-EE-016-development"])
    arguments = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project):
        parser.error("invalid development project")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", arguments.region):
        parser.error("invalid region")
    AcceptancePage.project = arguments.project
    AcceptancePage.region = arguments.region
    AcceptancePage.csrf = secrets.token_urlsafe(32)
    server = HTTPServer((PAGE_HOST, PAGE_PORT), AcceptancePage)
    print(f"Week 2 acceptance page ready at {PAGE_ORIGIN}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
