"""Non-mutating live proof for request, validation and upload-intent controls."""

from __future__ import annotations

import argparse
import json
import re

import requests

from tools.test_development_member_login import SafeTestFailure, cloud_cli


def call(origin: str, gateway: str, method: str, path: str, **kwargs):
    headers = {
        "X-Serverless-Authorization": f"Bearer {gateway}",
        "X-Request-Id": kwargs.pop("request_id", "ee-025-synthetic-check"),
        **kwargs.pop("headers", {}),
    }
    try:
        response = requests.request(
            method,
            origin + path,
            headers=headers,
            timeout=30,
            allow_redirects=False,
            **kwargs,
        )
    except requests.RequestException:
        raise SafeTestFailure("A security-check request could not reach the cloud service") from None
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response, payload


def assert_problem(response, payload, *, status: int, code: str) -> None:
    if response.status_code != status or payload.get("code") != code:
        raise SafeTestFailure(
            f"A synthetic request returned {response.status_code}; expected {status} {code}"
        )
    if not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("traceId", ""))):
        raise SafeTestFailure("A rejected request did not return a safe trace identifier")
    serialized = json.dumps(payload).lower()
    if any(marker in serialized for marker in ("bearer ", "password", "phone", "signature=")):
        raise SafeTestFailure("A rejected request exposed sensitive-looking information")
    if response.headers.get("Cache-Control") != "no-store":
        raise SafeTestFailure("A rejected request could be cached")


def run(origin: str, gateway: str) -> list[str]:
    checks: list[str] = []

    response, payload = call(origin, gateway, "GET", "/v1/admin/circles")
    assert_problem(response, payload, status=401, code="AUTHENTICATION_FAILED")
    checks.append("missing_application_authentication_was_rejected")

    response, payload = call(
        origin,
        gateway,
        "POST",
        "/v1/admin/events",
        json={"title": "x", "unexpected": "synthetic"},
    )
    assert_problem(response, payload, status=400, code="VALIDATION_FAILED")
    checks.append("invalid_and_unknown_fields_were_rejected_safely")

    response, payload = call(
        origin,
        gateway,
        "POST",
        "/v1/admin/events",
        data=b"x" * 1_048_577,
        headers={"Content-Type": "application/json"},
    )
    assert_problem(response, payload, status=413, code="PAYLOAD_TOO_LARGE")
    checks.append("oversized_request_body_was_rejected")

    base_upload = {
        "title": "Synthetic security check",
        "description": "No object is uploaded",
        "language": "en",
        "contentType": "application/pdf",
        "sizeBytes": 1024,
        "sha256": "a" * 64,
        "rightsConfirmed": True,
    }
    unsafe_uploads = [
        {**base_upload, "contentType": "text/plain"},
        {**base_upload, "rightsConfirmed": False},
        {**base_upload, "contentType": "audio/mpeg", "sizeBytes": 52_428_801},
    ]
    for body in unsafe_uploads:
        response, payload = call(
            origin, gateway, "POST", "/v1/contributor/content-uploads", json=body
        )
        assert_problem(response, payload, status=400, code="VALIDATION_FAILED")
    checks.append("unsupported_unowned_and_oversized_upload_intents_were_rejected")

    response, payload = call(
        origin,
        gateway,
        "GET",
        "/health",
        request_id="invalid request identifier with spaces",
    )
    if response.status_code != 200 or payload != {"status": "ok"}:
        raise SafeTestFailure("Health check failed after rejected synthetic requests")
    returned_request_id = response.headers.get("X-Request-Id", "")
    if returned_request_id == "invalid request identifier with spaces" or not re.fullmatch(
        r"[0-9a-f-]{36}", returned_request_id
    ):
        raise SafeTestFailure("Unsafe request identifier was not replaced")
    checks.append("unsafe_request_identifier_was_replaced")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-025-development"])
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
        checks = run(origin, cloud_cli("auth", "print-identity-token"))
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "state_changes_made": False,
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
