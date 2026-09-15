"""Live development proof for basic events using fictional accounts only.

The proof creates or reuses one temporary circle, confirms Administrator-only
event creation, verifies circle-filtered Member visibility and stored reminder
rules, then removes memberships and deactivates the circle. No notification is
sent and no credential, token or identifier is printed.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pyotp

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_content_uploads import private_inputs
from tools.test_development_member_login import SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof

CIRCLE_NAME = "Amiko EE-021 Event Test"


class EventProof:
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
            raise SafeTestFailure(
                f"{method} {safe_path} could not reach the cloud service"
            ) from error
        if status != expected or (code and payload.get("code") != code):
            safe_detail = ""
            safe_code = payload.get("code")
            safe_title = payload.get("title")
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
        return session["accessToken"], str(UUID(user["id"]))

    def prepare_circle(self) -> None:
        circles = self.call("GET", "/v1/admin/circles", access=self.admin_access)
        current = next((item for item in circles if item.get("name") == CIRCLE_NAME), None)
        body = {
            "name": CIRCLE_NAME,
            "description": "Fictional private event-visibility check",
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

    def visible(self, access: str, event_id: str) -> bool:
        page = self.call("GET", "/v1/events?period=upcoming&limit=50", access=access)
        return any(item.get("id") == event_id for item in page.get("items", []))

    def run(self, member_proofs: list[str]) -> list[str]:
        self.admin_access = self.staff_session("administrator")
        self.contributor_access = self.staff_session("contributor")
        for proof in member_proofs:
            access, member_id = self.member_session(proof)
            self.member_access.append(access)
            self.member_ids.append(member_id)
        checks: list[str] = []
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

            starts_at = datetime.now(UTC) + timedelta(days=2)
            event_body = {
                "title": f"Fictional EE-021 event {uuid4().hex[:8]}",
                "description": "Synthetic information-only event; no client data",
                "startsAt": starts_at.isoformat(),
                "endsAt": (starts_at + timedelta(hours=1)).isoformat(),
                "audience": "circles",
                "circleIds": [self.circle_id],
                "reminderMinutesBefore": [1440, 60],
            }
            self.call(
                "POST",
                "/v1/admin/events",
                access=self.contributor_access,
                body=event_body,
                expected=403,
                code="FORBIDDEN",
            )
            checks.append("contributors_cannot_create_events")

            created = self.call(
                "POST",
                "/v1/admin/events",
                access=self.admin_access,
                body=event_body,
                expected=201,
            )
            event_id = str(UUID(created["id"]))
            if (
                created.get("audience") != "circles"
                or created.get("circleIds") != [self.circle_id]
                or created.get("reminderMinutesBefore") != [1440, 60]
                or created.get("joinKind") != "information_only"
            ):
                raise SafeTestFailure("Created event did not retain its audience and reminder rules")
            checks.append("administrator_event_and_reminder_rules_were_saved")

            self.call(
                "GET", "/v1/events", access=self.contributor_access, expected=403, code="FORBIDDEN"
            )
            if not self.visible(self.member_access[0], event_id):
                raise SafeTestFailure("In-circle Member could not see the event")
            if self.visible(self.member_access[1], event_id):
                raise SafeTestFailure("Out-of-circle Member could see the event")
            checks.append("only_the_in_circle_member_could_see_the_event")

            self.call(
                "DELETE",
                f"/v1/admin/users/{self.member_ids[0]}/circles/{self.circle_id}/membership",
                access=self.admin_access,
                expected=204,
            )
            if self.visible(self.member_access[0], event_id):
                raise SafeTestFailure("Member retained event access after leaving the circle")
            checks.append("removing_membership_removed_event_access")
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
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-021-development"])
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
        checks = EventProof(
            origin, cloud_cli("auth", "print-identity-token"), private_inputs()
        ).run(
            [
                fictional_proof(args.project, identity_index=0),
                fictional_proof(args.project, identity_index=1),
            ]
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "fictional_accounts_only": True,
                    "real_notifications_sent": False,
                    "temporary_circle_deactivated": True,
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
