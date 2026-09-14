"""Private development session trial using only approved fictional phone identities.

Creates three synthetic Member sessions, then revokes them. Does not remove
existing devices, change account state, print credentials or send real SMS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from uuid import UUID, uuid4

from tools.test_development_member_login import (
    SafeTestFailure,
    cloud_cli,
    request_json,
    select_fictional_identity,
    verify_google_proof,
)


def fictional_proof(project, *, identity_index=0):
    operator = cloud_cli("auth", "print-access-token")
    status, config = request_json(
        "GET", f"https://identitytoolkit.googleapis.com/admin/v2/projects/{project}/config",
        params={"fields": "signIn.phoneNumber.testPhoneNumbers,client.apiKey"},
        headers={"Authorization": f"Bearer {operator}", "x-goog-user-project": project},
    )
    if status != 200:
        raise SafeTestFailure("Cannot read the development fictional-identity configuration")
    phone, code = select_fictional_identity(config, identity_index=identity_index)
    api_key = config.get("client", {}).get("apiKey")
    if not api_key:
        raise SafeTestFailure("Google phone configuration is missing")
    origin = "https://identitytoolkit.googleapis.com/v1"
    status, verification = request_json(
        "POST", f"{origin}/accounts:sendVerificationCode", params={"key": api_key},
        json={"phoneNumber": phone, "recaptchaToken": "NO_RECAPTCHA"},
    )
    if status != 200 or not verification.get("sessionInfo"):
        raise SafeTestFailure("Fictional verification could not start")
    status, identity = request_json(
        "POST", f"{origin}/accounts:signInWithPhoneNumber", params={"key": api_key},
        json={"sessionInfo": verification["sessionInfo"], "code": code},
    )
    if status != 200 or not identity.get("idToken"):
        raise SafeTestFailure("Fictional verification did not produce an identity")
    asyncio.run(verify_google_proof(project, identity["idToken"]))
    return identity["idToken"]


def check_sessions(origin, gateway, proof):
    checks = []

    def call(method, path, *, access=None, body=None, status=200, code=None):
        headers = {"X-Serverless-Authorization": f"Bearer {gateway}"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        result, payload = request_json(method, origin + path, headers=headers, json=body)
        if result != status or (code and payload.get("code") != code):
            raise SafeTestFailure("A development session expectation did not pass")
        return payload

    def create(platform):
        payload = call("POST", "/v1/auth/member/session", body={
            "providerIdToken": proof, "installationId": str(uuid4()), "platform": platform,
        })
        if (not payload.get("accessToken") or not payload.get("refreshToken")
                or payload.get("user", {}).get("role") != "member"
                or payload["user"].get("status") != "active"):
            raise SafeTestFailure("Unexpected synthetic Member session")
        return payload

    first, second = create("android"), create("ios")
    if first["user"]["id"] != second["user"]["id"]:
        raise SafeTestFailure("Cross-platform sign-in changed the Member identifier")
    checks.append("cross_platform_sign_in_preserves_member_identifier")
    renewed = call("POST", "/v1/auth/refresh", body={"refreshToken": first["refreshToken"]})
    if (renewed.get("user", {}).get("id") != first["user"]["id"]
            or renewed.get("accessToken") == first["accessToken"]
            or renewed.get("refreshToken") == first["refreshToken"]
            or not renewed.get("accessToken") or not renewed.get("refreshToken")):
        raise SafeTestFailure("Renewal did not replace credentials for the same Member")
    checks.append("renewal_replaces_credentials_without_changing_member")
    call("GET", "/v1/me/sessions", access=first["accessToken"], status=401,
         code="AUTHENTICATION_FAILED")
    call("GET", "/v1/me/sessions", access=renewed["accessToken"])
    checks.append("old_access_rejected_replacement_access_accepted")
    call("POST", "/v1/auth/refresh", body={"refreshToken": first["refreshToken"]}, status=409,
         code="REFRESH_TOKEN_REUSED")
    call("POST", "/v1/auth/refresh", body={"refreshToken": renewed["refreshToken"]}, status=401,
         code="SESSION_REVOKED")
    call("GET", "/v1/me/sessions", access=second["accessToken"])
    checks.append("reuse_revokes_only_its_session_family")
    call("POST", "/v1/auth/logout", access=second["accessToken"], status=204)
    call("POST", "/v1/auth/refresh", body={"refreshToken": second["refreshToken"]}, status=401,
         code="SESSION_REVOKED")
    checks.append("logout_blocks_automatic_renewal")
    third = create("android")
    devices = call("GET", "/v1/me/sessions", access=third["accessToken"])
    current = [device for device in devices if device.get("current")]
    if len(current) != 1:
        raise SafeTestFailure("Synthetic current device could not be identified")
    if str(UUID(current[0]["id"])) != current[0]["id"]:
        raise SafeTestFailure("Unexpected synthetic device identifier")
    call("DELETE", f"/v1/me/sessions/{current[0]['id']}", access=third["accessToken"], status=204)
    call("POST", "/v1/auth/refresh", body={"refreshToken": third["refreshToken"]}, status=401,
         code="SESSION_REVOKED")
    checks.append("device_removal_blocks_automatic_renewal")
    result, _ = request_json("GET", origin + "/health")
    if result not in {401, 403}:
        raise SafeTestFailure("Development service is unexpectedly public")
    checks.append("development_service_remains_private")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-011-development"])
    arguments = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project):
        parser.error("invalid project")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", arguments.region):
        parser.error("invalid region")
    try:
        origin = cloud_cli("run", "services", "describe", "ee-development-api",
                           f"--project={arguments.project}", f"--region={arguments.region}",
                           "--format=value(status.url)")
        if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
            raise SafeTestFailure("Unexpected development service origin")
        checks = check_sessions(origin, cloud_cli("auth", "print-identity-token"),
                                fictional_proof(arguments.project))
        print(json.dumps({"status": "passed", "checks": checks, "real_sms_sent": False}))
        return 0
    except SafeTestFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Private failure details suppressed"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
