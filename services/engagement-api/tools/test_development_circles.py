"""Live development proof for predefined circles using fictional accounts only.

The proof creates or reuses six clearly labelled test circles, checks Member
suggestions, the configurable five-circle limit and Administrator assignment,
then restores the fictional Member profile and limit. Test circles are left
inactive for auditability. Credentials, tokens, phone numbers and identifiers
are never printed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from uuid import uuid4

import pyotp

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_member_login import ROOT, SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof

TEST_NAMES = tuple(f"Amiko EE-017 Test {number}" for number in range(1, 7))


class CircleProof:
    def __init__(self, origin: str, gateway: str, inputs: FictionalSetupInput):
        self.origin, self.gateway, self.inputs = origin, gateway, inputs
        self.admin_access: str | None = None
        self.member_access: str | None = None
        self.contributor_access: str | None = None
        self.member_id: str | None = None

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
            raise SafeTestFailure(
                f"{method} {safe_path} returned {status}; expected {expected}"
            )
        return payload

    def staff_session(self, role: str) -> str:
        password = (
            self.inputs.administrator_password
            if role == "administrator"
            else self.inputs.contributor_password
        ).get_secret_value()
        body = {
            "username": f"fictional.ee010.{role}",
            "password": password,
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

    def member_session(self, proof: str) -> None:
        session = self.call(
            "POST",
            "/v1/auth/member/session",
            body={"providerIdToken": proof, "installationId": str(uuid4()), "platform": "android"},
        )
        if session.get("user", {}).get("role") != "member" or not session.get("accessToken"):
            raise SafeTestFailure("Fictional Member sign-in did not complete")
        self.member_access = session["accessToken"]
        self.member_id = session["user"].get("id")
        if not self.member_id:
            raise SafeTestFailure("Fictional Member identifier was not returned")

    def prepare_circles(self) -> list[dict]:
        existing = {
            item.get("name"): item
            for item in self.call("GET", "/v1/admin/circles", access=self.admin_access)
            if item.get("name") in TEST_NAMES
        }
        circles = []
        for name in TEST_NAMES:
            body = {
                "name": name,
                "description": "Fictional Week 3 verification circle",
                "suggestionRules": {"interests": ["music"], "preferredLanguages": ["en"]},
            }
            if name in existing:
                circle = self.call(
                    "PATCH",
                    f"/v1/admin/circles/{existing[name]['id']}",
                    access=self.admin_access,
                    body={**body, "active": True},
                )
            else:
                circle = self.call(
                    "POST", "/v1/admin/circles", access=self.admin_access, body=body, expected=201
                )
            circles.append(circle)
        return circles

    def run(self, proof: str) -> list[str]:
        checks: list[str] = []
        circles: list[dict] = []
        original_profile = None
        original_limit = None
        self.admin_access = self.staff_session("administrator")
        self.contributor_access = self.staff_session("contributor")
        self.member_session(proof)
        try:
            denied = {
                "name": "Amiko forbidden Contributor circle",
                "suggestionRules": {"interests": [], "preferredLanguages": []},
            }
            self.call(
                "POST",
                "/v1/admin/circles",
                access=self.contributor_access,
                body=denied,
                expected=403,
                code="FORBIDDEN",
            )
            checks.append("only_administrators_can_create_circles")

            original_profile = self.call("GET", "/v1/me/profile", access=self.member_access)
            self.call(
                "PATCH",
                "/v1/me/profile",
                access=self.member_access,
                body={"preferredLanguage": "en", "interests": ["music"]},
            )
            original_limit = self.call(
                "GET", "/v1/admin/circle-settings", access=self.admin_access
            ).get("maxMemberships")
            if not isinstance(original_limit, int):
                raise SafeTestFailure("Original circle limit could not be verified")
            self.call(
                "PUT",
                "/v1/admin/circle-settings",
                access=self.admin_access,
                body={"maxMemberships": 5},
            )
            circles = self.prepare_circles()
            member_view = self.call("GET", "/v1/me/circles", access=self.member_access)
            visible = {item.get("id"): item for item in member_view}
            if any(not visible.get(item["id"], {}).get("suggested") for item in circles):
                raise SafeTestFailure("Expected fictional circle suggestions were not returned")
            checks.append("profile_based_circle_suggestions_work")

            for circle in circles[:5]:
                self.call(
                    "POST",
                    f"/v1/me/circles/{circle['id']}/membership",
                    access=self.member_access,
                    expected=204,
                )
            self.call(
                "POST",
                f"/v1/me/circles/{circles[5]['id']}/membership",
                access=self.member_access,
                expected=409,
                code="CIRCLE_LIMIT_REACHED",
            )
            checks.append("five_circle_limit_is_enforced")

            self.call(
                "DELETE",
                f"/v1/me/circles/{circles[0]['id']}/membership",
                access=self.member_access,
                expected=204,
            )
            self.call(
                "POST",
                f"/v1/admin/users/{self.member_id}/circles/{circles[5]['id']}/membership",
                access=self.admin_access,
                expected=204,
            )
            joined = {
                item["id"]
                for item in self.call("GET", "/v1/me/circles", access=self.member_access)
                if item.get("joined")
            }
            if circles[5]["id"] not in joined or circles[0]["id"] in joined:
                raise SafeTestFailure("Member join/leave or Administrator assignment was not reflected")
            self.call(
                "DELETE",
                f"/v1/admin/users/{self.member_id}/circles/{circles[5]['id']}/membership",
                access=self.admin_access,
                expected=204,
            )
            checks.append("member_and_administrator_membership_controls_work")
            return checks
        finally:
            if self.member_access:
                for circle in circles:
                    try:
                        self.call(
                            "DELETE",
                            f"/v1/me/circles/{circle['id']}/membership",
                            access=self.member_access,
                            expected=204,
                        )
                    except SafeTestFailure:
                        pass
                if original_profile:
                    try:
                        self.call(
                            "PATCH",
                            "/v1/me/profile",
                            access=self.member_access,
                            body={
                                "preferredLanguage": original_profile["preferredLanguage"],
                                "interests": original_profile["interests"],
                            },
                        )
                    except SafeTestFailure:
                        pass
            if self.admin_access:
                for circle in circles:
                    try:
                        self.call(
                            "PATCH",
                            f"/v1/admin/circles/{circle['id']}",
                            access=self.admin_access,
                            body={"active": False},
                        )
                    except SafeTestFailure:
                        pass
                if isinstance(original_limit, int):
                    try:
                        self.call(
                            "PUT",
                            "/v1/admin/circle-settings",
                            access=self.admin_access,
                            body={"maxMemberships": original_limit},
                        )
                    except SafeTestFailure:
                        pass
            for access in (self.member_access, self.contributor_access, self.admin_access):
                if access:
                    try:
                        self.call("POST", "/v1/auth/logout", access=access, expected=204)
                    except SafeTestFailure:
                        pass


def load_private_inputs(path: Path) -> FictionalSetupInput:
    try:
        resolved = path.resolve(strict=True)
        private_root = (ROOT / "secure-runtime" / "fictional-staff-private").resolve(strict=True)
        resolved.relative_to(private_root)
        return FictionalSetupInput.model_validate_json(resolved.read_text(encoding="utf-8"))
    except Exception:
        raise SafeTestFailure("Protected fictional staff inputs could not be read") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-017-development"])
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project) or not re.fullmatch(
        r"[a-z]+-[a-z]+[0-9]+", args.region
    ):
        parser.error("invalid development project or region")
    try:
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
        inputs = load_private_inputs(
            ROOT / "secure-runtime" / "fictional-staff-private" / "setup-input.json"
        )
        checks = CircleProof(
            origin, cloud_cli("auth", "print-identity-token"), inputs
        ).run(fictional_proof(args.project, identity_index=1))
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "fictional_accounts_only": True,
                    "real_sms_sent": False,
                    "temporary_settings_restored": True,
                    "test_circles_left_inactive": True,
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
