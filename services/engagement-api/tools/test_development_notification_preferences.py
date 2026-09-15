"""Development-only notification-preference trial using a fictional Member.

The trial saves a temporary preference set, verifies that it can be read back,
then restores the fictional account's original preferences. It never sends an
SMS or notification and never prints credentials, tokens, phone numbers or IDs.
"""

from __future__ import annotations

import argparse
import json
import re
from uuid import uuid4

from tools.test_development_member_login import SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof


def check_notification_preferences(origin: str, gateway: str, proof: str) -> list[str]:
    access = None
    original = None
    checks: list[str] = []

    def call(method: str, path: str, *, body=None, expected: int = 200):
        headers = {"X-Serverless-Authorization": f"Bearer {gateway}"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        status, response = request_json(method, origin + path, headers=headers, json=body)
        if status != expected:
            raise SafeTestFailure("A development notification-preference expectation did not pass")
        return response

    session = call(
        "POST",
        "/v1/auth/member/session",
        body={"providerIdToken": proof, "installationId": str(uuid4()), "platform": "ios"},
    )
    access = session.get("accessToken")
    if not access or session.get("user", {}).get("role") != "member":
        raise SafeTestFailure("Synthetic Member session did not succeed")

    try:
        original_response = call("GET", "/v1/me/notification-preferences")
        original = {
            "eventReminders": original_response.get("eventReminders"),
            "contentUpdates": original_response.get("contentUpdates"),
            "deliveryWindow": original_response.get("deliveryWindow"),
        }
        if not isinstance(original["eventReminders"], bool) or not isinstance(
            original["contentUpdates"], bool
        ) or not isinstance(original["deliveryWindow"], dict):
            raise SafeTestFailure("The original fictional preferences were not valid")
        checks.append("safe_defaults_or_existing_preferences_read")

        temporary = {
            "eventReminders": False,
            "contentUpdates": True,
            "deliveryWindow": {
                "enabled": True,
                "timeZone": "Asia/Kolkata",
                "startLocalTime": "10:00",
                "endLocalTime": "18:00",
            },
        }
        saved = call("PUT", "/v1/me/notification-preferences", body=temporary)
        read_back = call("GET", "/v1/me/notification-preferences")
        for response in (saved, read_back):
            if any(response.get(key) != value for key, value in temporary.items()):
                raise SafeTestFailure("Saved notification choices were not returned unchanged")
        checks.append("member_choices_saved_and_read_back")

        call(
            "PUT",
            "/v1/me/notification-preferences",
            body={**temporary, "unknown": True},
            expected=400,
        )
        checks.append("unexpected_fields_rejected")
        return checks
    finally:
        if access and original:
            call("PUT", "/v1/me/notification-preferences", body=original)
        if access:
            call("POST", "/v1/auth/logout", expected=204)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-022-development"])
    arguments = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project) or not re.fullmatch(
        r"[a-z]+-[a-z]+[0-9]+", arguments.region
    ):
        parser.error("invalid development project or region")
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
        checks = check_notification_preferences(
            origin,
            cloud_cli("auth", "print-identity-token"),
            fictional_proof(arguments.project, identity_index=1),
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "real_sms_sent": False,
                    "notification_sent": False,
                    "original_preferences_restored": True,
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
