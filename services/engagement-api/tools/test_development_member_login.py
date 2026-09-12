"""Test private development login using only cloud-configured fictional identities.

Never prints API keys, verification codes, identity tokens, session tokens or
Member identifiers. Retains the fictional Member and its development sessions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import requests

from app.google_phone_identity import GooglePhoneIdentityVerifier

ROOT = Path(__file__).parents[3]


class SafeTestFailure(RuntimeError):
    pass


def cloud_cli(*arguments: str) -> str:
    environment = dict(os.environ)
    environment["CLOUDSDK_CONFIG"] = str(ROOT / "secure-runtime" / "gcloud-config")
    environment["TMP"] = str(ROOT / "secure-runtime" / "temp")
    environment["TEMP"] = environment["TMP"]
    executable = ROOT / "tools-runtime" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
    result = subprocess.run(  # noqa: S603 - fixed executable and validated arguments
        [str(executable), *arguments, "--quiet"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise SafeTestFailure("Google Cloud authentication or discovery failed")
    return result.stdout.strip()


def request_json(method: str, url: str, **kwargs):
    try:
        response = requests.request(
            method, url, timeout=30, allow_redirects=False, **kwargs
        )
    except requests.RequestException:
        raise SafeTestFailure("A test network request failed") from None
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload


def select_fictional_identity(config):
    pairs = config.get("signIn", {}).get("phoneNumber", {}).get("testPhoneNumbers", {})
    if not pairs:
        raise SafeTestFailure("No fictional cloud test identities are configured")
    phone, code = next(iter(pairs.items()))
    if not phone.startswith("+91") or not re.fullmatch(r"[0-9]{6}", str(code)):
        raise SafeTestFailure("Fictional test identity must match the approved India region")
    return phone, str(code)


async def verify_google_proof(project, proof):
    verifier = GooglePhoneIdentityVerifier(project, project)
    try:
        await verifier.verify(proof)
    finally:
        verifier.close()


def run_test(arguments):
    project = arguments.project
    operator_token = cloud_cli("auth", "print-access-token")
    status, config = request_json(
        "GET",
        f"https://identitytoolkit.googleapis.com/admin/v2/projects/{project}/config",
        headers={"Authorization": f"Bearer {operator_token}", "x-goog-user-project": project},
    )
    if status != 200:
        raise SafeTestFailure("Cannot read the development fictional-identity configuration")
    phone, code = select_fictional_identity(config)
    api_key = config.get("client", {}).get("apiKey")
    if not api_key:
        raise SafeTestFailure("Google phone sign-in client configuration is missing")
    provider_origin = "https://identitytoolkit.googleapis.com/v1"
    status, verification = request_json(
        "POST", f"{provider_origin}/accounts:sendVerificationCode",
        params={"key": api_key},
        json={"phoneNumber": phone, "recaptchaToken": "NO_RECAPTCHA"},
    )
    if status != 200 or not verification.get("sessionInfo"):
        raise SafeTestFailure("Google did not start the fictional phone verification")
    checks = ["fictional_phone_verification_started"]
    wrong_code = f"{(int(code) + 1) % 1_000_000:06d}"
    status, _ = request_json(
        "POST", f"{provider_origin}/accounts:signInWithPhoneNumber",
        params={"key": api_key},
        json={"sessionInfo": verification["sessionInfo"], "code": wrong_code},
    )
    if status != 400:
        raise SafeTestFailure("Wrong fictional verification code was not rejected")
    checks.append("wrong_verification_code_rejected")
    status, identity = request_json(
        "POST", f"{provider_origin}/accounts:signInWithPhoneNumber",
        params={"key": api_key},
        json={"sessionInfo": verification["sessionInfo"], "code": code},
    )
    if status != 200 or not identity.get("idToken"):
        raise SafeTestFailure("Correct fictional verification code did not produce a Google identity")
    asyncio.run(verify_google_proof(project, identity["idToken"]))
    checks.append("genuine_google_phone_identity_verified")
    origin = cloud_cli(
        "run", "services", "describe", arguments.service,
        f"--project={project}", f"--region={arguments.region}",
        "--format=value(status.url)",
    )
    if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", origin):
        raise SafeTestFailure("Unexpected development Cloud Run origin")
    gateway_token = cloud_cli(
        "auth", "print-identity-token",
        f"--impersonate-service-account=ee-development-github@{project}.iam.gserviceaccount.com",
        f"--audiences={origin}",
    )
    headers = {"Authorization": f"Bearer {gateway_token}"}
    member_ids = []
    for platform in ["android", "ios"]:
        status, session = request_json(
            "POST", f"{origin}/v1/auth/member/session", headers=headers,
            json={
                "providerIdToken": identity["idToken"],
                "installationId": str(uuid4()),
                "platform": platform,
            },
        )
        if status != 200 or not session.get("accessToken") or not session.get("refreshToken"):
            raise SafeTestFailure(f"Development {platform} Member session did not succeed")
        if session.get("user", {}).get("role") != "member":
            raise SafeTestFailure("Unexpected Member-session role")
        member_ids.append(session["user"]["id"])
        checks.append(f"{platform}_member_session_created")
    if member_ids[0] != member_ids[1]:
        raise SafeTestFailure("Repeat sign-in created duplicate Member accounts")
    checks.append("repeat_cross_platform_login_reuses_one_member")
    status, rejected = request_json(
        "POST", f"{origin}/v1/auth/member/session", headers=headers,
        json={
            "providerIdToken": "synthetic-invalid-provider-proof",
            "installationId": str(uuid4()),
            "platform": "android",
        },
    )
    if status != 401 or rejected.get("code") != "AUTHENTICATION_FAILED":
        raise SafeTestFailure("Invalid provider proof was not safely rejected")
    checks.append("invalid_provider_proof_rejected")
    status, _ = request_json("GET", f"{origin}/health")
    if status not in {401, 403}:
        raise SafeTestFailure("Development service was unexpectedly public")
    checks.append("development_service_remains_private")
    print(json.dumps({"status": "passed", "checks": checks, "real_sms_sent": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--service", default="ee-development-api")
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-009-development"])
    arguments = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", arguments.project):
        parser.error("invalid project")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", arguments.region):
        parser.error("invalid region")
    if arguments.service != "ee-development-api":
        parser.error("this test is restricted to the development service")
    try:
        run_test(arguments)
    except SafeTestFailure as failure:
        print(json.dumps({"status": "failed", "reason": str(failure)}))
        return 1
    except Exception:
        print(json.dumps({
            "status": "failed", "reason": "Unexpected test failure; private details suppressed"
        }))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
