"""Development-only profile trial using a configured fictional phone identity.

Retains clearly labelled synthetic profile data. Refuses to overwrite another
profile. Never prints identity/session tokens, phone numbers or member IDs.
"""
from __future__ import annotations

import argparse
import json
import re
from uuid import uuid4

from tools.test_development_member_login import SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof

PROFILE_NAME = "Fictional profile test"


def check_profiles(origin, gateway, proof):
    access = None
    checks = []

    def call(method, path, *, body=None, expected=200):
        headers = {"X-Serverless-Authorization": f"Bearer {gateway}"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        status, response = request_json(method, origin + path, headers=headers, json=body)
        if status != expected:
            raise SafeTestFailure("A development profile expectation did not pass")
        return response

    session = call("POST", "/v1/auth/member/session", body={
        "providerIdToken": proof, "installationId": str(uuid4()), "platform": "ios",
    })
    access = session.get("accessToken")
    if not access or session.get("user", {}).get("role") != "member":
        raise SafeTestFailure("Synthetic Member session did not succeed")
    try:
        headers = {"X-Serverless-Authorization": f"Bearer {gateway}", "Authorization": f"Bearer {access}"}
        status, existing = request_json("GET", origin + "/v1/me/profile", headers=headers)
        if status != 404 and (status != 200 or existing.get("displayName") != PROFILE_NAME):
            raise SafeTestFailure("Will not overwrite an existing non-fixture profile")
        created = call("PATCH", "/v1/me/profile", body={
            "displayName": PROFILE_NAME, "preferredLanguage": "en", "ageGroup": "55+",
            "interests": ["Fictional interest"],
            "broadLocation": {"countryCode": "IN", "state": "Synthetic state", "city": "Synthetic city"},
            "notificationWindow": {
                "enabled": True, "timeZone": "Asia/Kolkata",
                "startLocalTime": "09:00", "endLocalTime": "18:00",
            },
        })
        if (created.get("id") != session["user"]["id"] or created.get("role") != "member"
                or created.get("status") != "active"):
            raise SafeTestFailure("Profile ownership or access changed unexpectedly")
        checks.append("approved_profile_fields_saved_for_same_member")
        for language in ["bn", "hi", "en"]:
            call("PATCH", "/v1/me/profile", body={"preferredLanguage": language})
            profile = call("GET", "/v1/me/profile")
            if (profile.get("preferredLanguage") != language or profile.get("ageGroup") != "55+"
                    or profile.get("displayName") != PROFILE_NAME
                    or profile.get("interests") != ["Fictional interest"]
                    or profile.get("broadLocation", {}).get("city") != "Synthetic city"
                    or profile.get("notificationWindow", {}).get("timeZone") != "Asia/Kolkata"):
                raise SafeTestFailure("Language or omitted profile fields were not preserved")
        checks.append("english_bengali_hindi_saved_and_omitted_fields_preserved")
        call("PATCH", "/v1/me/profile", body={"preferredLanguage": "fr"}, expected=400)
        call("PATCH", "/v1/me/profile", body={"role": "administrator"}, expected=400)
        checks.append("unsupported_language_and_self_assigned_permissions_rejected")
        changed = call("PATCH", "/v1/me/profile", body={"ageGroup": "Fictional younger group"})
        if changed.get("status") != "active":
            raise SafeTestFailure("Age label incorrectly restricted access")
        call("PATCH", "/v1/me/profile", body={"ageGroup": "55+"})
        checks.append("age_label_is_not_an_access_restriction")
        renewed = call("POST", "/v1/auth/refresh", body={"refreshToken": session["refreshToken"]})
        access = renewed.get("accessToken")
        if (not access or renewed.get("user", {}).get("id") != session["user"]["id"]
                or renewed["user"].get("preferredLanguage") != "en"
                or not renewed["user"].get("profileComplete")):
            raise SafeTestFailure("Saved-login renewal did not reflect the saved profile")
        call("GET", "/v1/me/profile")
        checks.append("renewed_login_reads_saved_english_profile")
        return checks
    finally:
        if access:
            call("POST", "/v1/auth/logout", expected=204)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-013-development"])
    args = parser.parse_args()
    if (not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project)
            or not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", args.region)):
        parser.error("invalid development project or region")
    try:
        origin = cloud_cli("run", "services", "describe", "ee-development-api", f"--project={args.project}",
                           f"--region={args.region}", "--format=value(status.url)")
        if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
            raise SafeTestFailure("Unexpected development service origin")
        checks = check_profiles(origin, cloud_cli("auth", "print-identity-token"),
                                fictional_proof(args.project, identity_index=1))
        print(json.dumps({"status": "passed", "checks": checks, "real_sms_sent": False,
                          "fixture_profile_retained": True, "profile_photo_tested": False}))
        return 0
    except SafeTestFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Private failure details suppressed"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
