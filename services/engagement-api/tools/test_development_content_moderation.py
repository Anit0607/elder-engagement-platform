"""Live development proof for private Administrator content moderation.

Uses only the synthetic EE-018 uploads. Credentials, tokens, identifiers and
signed preview links are never printed.
"""

from __future__ import annotations

import argparse
import json
import re
from uuid import UUID, uuid4

import pyotp
import requests

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_content_uploads import private_inputs
from tools.test_development_member_login import SafeTestFailure, cloud_cli, request_json

EXPECTED = {
    "Synthetic video upload check": "video",
    "Synthetic audio upload check": "audio",
    "Synthetic PDF upload check": "pdf",
}


class ModerationProof:
    def __init__(self, origin: str, gateway: str, inputs: FictionalSetupInput):
        self.origin, self.gateway, self.inputs = origin, gateway, inputs
        self.admin_access: str | None = None
        self.contributor_access: str | None = None

    def call(self, method: str, path: str, *, access=None, body=None, expected=200, code=None):
        headers = {"X-Serverless-Authorization": f"Bearer {self.gateway}"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        safe_path = re.sub(
            r"/[0-9a-f]{8}-[0-9a-f-]{27,}", "/{identifier}", path, flags=re.IGNORECASE
        )
        try:
            status, payload = request_json(
                method, self.origin + path, headers=headers, json=body
            )
        except SafeTestFailure as error:
            raise SafeTestFailure(f"{method} {safe_path} could not reach the cloud service") from error
        if status != expected or (code and payload.get("code") != code):
            raise SafeTestFailure(f"{method} {safe_path} returned {status}; expected {expected}")
        return payload

    def staff_session(self, role: str) -> str:
        body = {
            "username": f"fictional.ee010.{role}",
            "password": (
                self.inputs.administrator_password
                if role == "administrator"
                else self.inputs.contributor_password
            ).get_secret_value(),
            "installationId": str(uuid4()),
            "platform": "web",
        }
        if role == "administrator":
            body["secondFactorCode"] = pyotp.TOTP(
                self.inputs.administrator_seed.get_secret_value()
            ).now()
        session = self.call("POST", "/v1/auth/staff/session", body=body)
        if session.get("user", {}).get("role") != role or not session.get("accessToken"):
            raise SafeTestFailure("Fictional staff sign-in did not return the expected role")
        return session["accessToken"]

    def run(self) -> list[str]:
        self.admin_access = self.staff_session("administrator")
        self.contributor_access = self.staff_session("contributor")
        checks: list[str] = []
        try:
            self.call(
                "GET",
                "/v1/admin/content-moderation",
                access=self.contributor_access,
                expected=403,
                code="FORBIDDEN",
            )
            checks.append("contributor_cannot_open_administrator_review_queue")

            queue = self.call(
                "GET", "/v1/admin/content-moderation", access=self.admin_access
            )
            items = {item.get("title"): item for item in queue if item.get("title") in EXPECTED}
            if set(items) != set(EXPECTED):
                raise SafeTestFailure("The three synthetic pending uploads were not all found")

            for title, expected_kind in EXPECTED.items():
                item = items[title]
                try:
                    content_id = str(UUID(item["contentItemId"]))
                except (KeyError, TypeError, ValueError) as error:
                    raise SafeTestFailure("A synthetic queue item did not have a valid identifier") from error
                if item.get("kind") != expected_kind:
                    raise SafeTestFailure("A synthetic queue item had an unexpected content kind")
                preview = self.call(
                    "GET",
                    f"/v1/admin/content-moderation/{content_id}/preview",
                    access=self.admin_access,
                )
                preview_url = preview.get("previewUrl")
                if not isinstance(preview_url, str) or not preview_url.startswith(
                    "https://storage.googleapis.com/"
                ):
                    raise SafeTestFailure("The private preview authorisation was not usable")
                try:
                    response = requests.get(preview_url, timeout=30, allow_redirects=False)
                except requests.RequestException as error:
                    raise SafeTestFailure("A private synthetic preview could not be opened") from error
                if response.status_code != 200 or not response.content:
                    raise SafeTestFailure("A private synthetic preview was empty or unavailable")

            checks.append("all_synthetic_formats_have_short_lived_private_previews")
            decisions = {
                "Synthetic video upload check": {
                    "outcome": "approved",
                    "reasonCode": "approved",
                },
                "Synthetic audio upload check": {
                    "outcome": "rejected",
                    "reasonCode": "poor_quality",
                },
                "Synthetic PDF upload check": {
                    "outcome": "rejected",
                    "reasonCode": "other",
                    "note": "Synthetic EE-019 workflow verification",
                },
            }
            for title, body in decisions.items():
                content_id = items[title]["contentItemId"]
                receipt = self.call(
                    "POST",
                    f"/v1/admin/content-moderation/{content_id}/decision",
                    access=self.admin_access,
                    body=body,
                )
                if receipt.get("status") != body["outcome"] or receipt.get("published") is not False:
                    raise SafeTestFailure("A moderation decision was not recorded privately")
            checks.append("approve_and_reject_reasons_are_recorded_without_publication")

            content_id = items["Synthetic video upload check"]["contentItemId"]
            self.call(
                "POST",
                f"/v1/admin/content-moderation/{content_id}/decision",
                access=self.admin_access,
                body={"outcome": "approved", "reasonCode": "approved"},
                expected=409,
                code="CONFLICT",
            )
            checks.append("a_final_decision_cannot_be_repeated")
            return checks
        finally:
            for access in (self.contributor_access, self.admin_access):
                if access:
                    try:
                        self.call("POST", "/v1/auth/logout", access=access, expected=204)
                    except SafeTestFailure:
                        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-019-development"])
    arguments = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project):
        parser.error("invalid development project")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", arguments.region):
        parser.error("invalid region")
    try:
        origin = cloud_cli(
            "run",
            "services",
            "describe",
            "ee-development-api",
            f"--project={arguments.project}",
            f"--region={arguments.region}",
            "--format=value(status.url)",
        )
        if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
            raise SafeTestFailure("Unexpected development service origin")
        checks = ModerationProof(
            origin, cloud_cli("auth", "print-identity-token"), private_inputs()
        ).run()
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "synthetic_material_only": True,
                    "material_publicly_visible": False,
                    "secrets_printed": False,
                }
            )
        )
        return 0
    except SafeTestFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Private failure details suppressed"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
