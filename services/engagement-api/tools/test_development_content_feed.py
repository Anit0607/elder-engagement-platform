"""Live private-development proof for the circle-filtered Member feed.

The proof uses fictional accounts, one temporary test circle and the approved
synthetic MP4 only. It prints no credential, token, identifier or signed link.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

import pyotp
import requests

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_content_uploads import private_inputs
from tools.test_development_member_login import ROOT, SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof

CIRCLE_NAME = "Amiko EE-020 Audience Test"


class FeedProof:
    def __init__(self, origin: str, gateway: str, inputs: FictionalSetupInput):
        self.origin, self.gateway, self.inputs = origin, gateway, inputs
        self.admin_access: str | None = None
        self.contributor_access: str | None = None
        self.member_access: list[str] = []
        self.member_ids: list[str] = []
        self.circle_id: str | None = None

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
            safe_code = payload.get("code")
            safe_title = payload.get("title")
            safe_detail = ""
            if isinstance(safe_code, str) and re.fullmatch(r"[A-Z0-9_]{1,64}", safe_code):
                safe_detail += f"; code {safe_code}"
            if isinstance(safe_title, str) and 1 <= len(safe_title) <= 160:
                safe_detail += f"; reason {safe_title}"
            raise SafeTestFailure(
                f"{method} {safe_path} returned {status}; expected {expected}{safe_detail}"
            )
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

    def member_session(self, proof: str) -> tuple[str, str]:
        session = self.call(
            "POST",
            "/v1/auth/member/session",
            body={
                "providerIdToken": proof,
                "installationId": str(uuid4()),
                "platform": "android",
            },
        )
        user = session.get("user", {})
        if user.get("role") != "member" or not session.get("accessToken") or not user.get("id"):
            raise SafeTestFailure("Fictional Member sign-in did not complete")
        return session["accessToken"], user["id"]

    def prepare_circle(self):
        circles = self.call("GET", "/v1/admin/circles", access=self.admin_access)
        current = next((item for item in circles if item.get("name") == CIRCLE_NAME), None)
        body = {
            "name": CIRCLE_NAME,
            "description": "Fictional private feed-isolation check",
            "suggestionRules": {"interests": [], "preferredLanguages": []},
        }
        if current:
            circle = self.call(
                "PATCH",
                f"/v1/admin/circles/{current['id']}",
                access=self.admin_access,
                body={**body, "active": True},
            )
        else:
            circle = self.call(
                "POST", "/v1/admin/circles", access=self.admin_access, body=body, expected=201
            )
        self.circle_id = str(UUID(circle["id"]))

    def upload_and_approve(self, sample: Path) -> str:
        content = sample.read_bytes()
        title = f"Synthetic EE-020 circle feed check {uuid4().hex[:8]}"
        started = self.call(
            "POST",
            "/v1/contributor/content-uploads",
            access=self.contributor_access,
            body={
                "title": title,
                "description": "Artificial feed verification material; not client content",
                "language": "en",
                "contentType": "video/mp4",
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "rightsConfirmed": True,
            },
            expected=201,
        )
        try:
            upload_id = str(UUID(started["uploadId"]))
            upload_url = started["uploadUrl"]
            required_headers = started["requiredHeaders"]
        except (KeyError, TypeError, ValueError) as error:
            raise SafeTestFailure("Synthetic upload authorisation was invalid") from error
        uploaded = requests.put(
            upload_url,
            data=content,
            headers=required_headers,
            timeout=60,
            allow_redirects=False,
        )
        if uploaded.status_code not in {200, 201}:
            raise SafeTestFailure("Synthetic video did not reach private storage")
        receipt = self.call(
            "POST",
            f"/v1/contributor/content-uploads/{upload_id}/complete",
            access=self.contributor_access,
        )
        content_id = str(UUID(receipt["contentItemId"]))
        queue = self.call("GET", "/v1/admin/content-moderation", access=self.admin_access)
        if not any(item.get("contentItemId") == content_id for item in queue):
            raise SafeTestFailure("Synthetic video did not enter the Administrator queue")
        decision = self.call(
            "POST",
            f"/v1/admin/content-moderation/{content_id}/decision",
            access=self.admin_access,
            body={"outcome": "approved", "reasonCode": "approved"},
        )
        if decision.get("status") != "approved" or decision.get("published") is not False:
            raise SafeTestFailure("Synthetic video approval was not private")
        return content_id

    def feed_contains(self, access: str, content_id: str) -> bool:
        page = self.call("GET", "/v1/feed?limit=50", access=access)
        return any(item.get("contentItemId") == content_id for item in page.get("items", []))

    def run(self, member_proofs: list[str], sample: Path) -> list[str]:
        self.admin_access = self.staff_session("administrator")
        self.contributor_access = self.staff_session("contributor")
        for proof in member_proofs:
            access, member_id = self.member_session(proof)
            self.member_access.append(access)
            self.member_ids.append(member_id)
        checks: list[str] = []
        content_id: str | None = None
        self.prepare_circle()
        try:
            for member_id in self.member_ids:
                self.call(
                    "DELETE",
                    f"/v1/admin/users/{member_id}/circles/{self.circle_id}/membership",
                    access=self.admin_access,
                    expected=204,
                )
            self.call(
                "POST",
                f"/v1/admin/users/{self.member_ids[0]}/circles/{self.circle_id}/membership",
                access=self.admin_access,
                expected=204,
            )
            content_id = self.upload_and_approve(sample)
            self.call(
                "GET", "/v1/feed", access=self.contributor_access, expected=403, code="FORBIDDEN"
            )
            checks.append("contributors_cannot_read_the_member_feed")

            published = self.call(
                "POST",
                f"/v1/admin/content/{content_id}/publication",
                access=self.admin_access,
                body={"audience": "circles", "circleIds": [self.circle_id]},
            )
            if published.get("audience") != "circles" or published.get("circleIds") != [
                self.circle_id
            ]:
                raise SafeTestFailure("Publication did not retain the selected circle")
            checks.append("approved_media_was_promoted_and_audience_recorded")

            if not self.feed_contains(self.member_access[0], content_id):
                raise SafeTestFailure("In-circle Member could not see the published item")
            if self.feed_contains(self.member_access[1], content_id):
                raise SafeTestFailure("Out-of-circle Member could see the published item")
            checks.append("only_the_in_circle_member_could_see_the_item")

            media = self.call(
                "GET", f"/v1/feed/{content_id}/media", access=self.member_access[0]
            )
            media_url = media.get("mediaUrl")
            if not isinstance(media_url, str) or not media_url.startswith(
                "https://storage.googleapis.com/"
            ):
                raise SafeTestFailure("Member media authorisation was invalid")
            opened = requests.get(media_url, timeout=30, allow_redirects=False)
            if opened.status_code != 200 or hashlib.sha256(opened.content).digest() != hashlib.sha256(
                sample.read_bytes()
            ).digest():
                raise SafeTestFailure("Approved synthetic media could not be opened")
            self.call(
                "GET",
                f"/v1/feed/{content_id}/media",
                access=self.member_access[1],
                expected=404,
                code="NOT_FOUND",
            )
            checks.append("private_media_link_obeyed_the_same_circle_rule")

            self.call(
                "DELETE",
                f"/v1/admin/users/{self.member_ids[0]}/circles/{self.circle_id}/membership",
                access=self.admin_access,
                expected=204,
            )
            if self.feed_contains(self.member_access[0], content_id):
                raise SafeTestFailure("A Member retained feed access after leaving the circle")
            self.call(
                "GET",
                f"/v1/feed/{content_id}/media",
                access=self.member_access[0],
                expected=404,
                code="NOT_FOUND",
            )
            checks.append("removing_membership_removed_feed_and_media_access")
            return checks
        finally:
            if self.circle_id and self.admin_access:
                for member_id in self.member_ids:
                    try:
                        self.call(
                            "DELETE",
                            f"/v1/admin/users/{member_id}/circles/{self.circle_id}/membership",
                            access=self.admin_access,
                            expected=204,
                        )
                    except SafeTestFailure:
                        pass
                try:
                    self.call(
                        "PATCH",
                        f"/v1/admin/circles/{self.circle_id}",
                        access=self.admin_access,
                        body={"active": False},
                    )
                except SafeTestFailure:
                    pass
            for access in [*self.member_access, self.contributor_access, self.admin_access]:
                if access:
                    try:
                        self.call("POST", "/v1/auth/logout", access=access, expected=204)
                    except SafeTestFailure:
                        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-020-development"])
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project) or not re.fullmatch(
        r"[a-z]+-[a-z]+[0-9]+", args.region
    ):
        parser.error("invalid development project or region")
    try:
        sample = (ROOT / "output" / "synthetic-media" / "amiko-synthetic-upload-sample.mp4").resolve(
            strict=True
        )
        sample.relative_to((ROOT / "output" / "synthetic-media").resolve(strict=True))
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
            raise SafeTestFailure("Unexpected development service origin")
        checks = FeedProof(
            origin, cloud_cli("auth", "print-identity-token"), private_inputs()
        ).run(
            [
                fictional_proof(args.project, identity_index=0),
                fictional_proof(args.project, identity_index=1),
            ],
            sample,
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "synthetic_material_only": True,
                    "fictional_accounts_only": True,
                    "temporary_circle_deactivated": True,
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
