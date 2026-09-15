"""Development-only profile-photo trial using a fictional Member and synthetic image.

Keeps the final sanitised fixture photo so profile reads remain testable. Never
prints identity/session tokens, phone numbers, member IDs or signed URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from uuid import UUID, uuid4

import requests
from PIL import Image, PngImagePlugin

from tools.test_development_member_login import SafeTestFailure, cloud_cli, request_json
from tools.test_development_member_sessions import fictional_proof
from tools.test_development_profiles import PROFILE_NAME


def synthetic_png() -> bytes:
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "Synthetic metadata that must not be retained")
    Image.new("RGB", (48, 36), (49, 102, 168)).save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def check_profile_photo(origin: str, gateway: str, proof: str) -> list[str]:
    access = None
    checks: list[str] = []

    def call(method: str, path: str, *, body=None, expected: int = 200):
        headers = {"X-Serverless-Authorization": f"Bearer {gateway}"}
        if access:
            headers["Authorization"] = f"Bearer {access}"
        status, response = request_json(method, origin + path, headers=headers, json=body)
        if status != expected:
            raise SafeTestFailure("A development profile-photo expectation did not pass")
        return response

    session = call(
        "POST",
        "/v1/auth/member/session",
        body={"providerIdToken": proof, "installationId": str(uuid4()), "platform": "android"},
    )
    access = session.get("accessToken")
    if not access or session.get("user", {}).get("role") != "member":
        raise SafeTestFailure("Synthetic Member session did not succeed")

    try:
        profile = call("GET", "/v1/me/profile")
        if profile.get("displayName") != PROFILE_NAME:
            raise SafeTestFailure("Will not attach a photo to a non-fixture profile")

        photo = synthetic_png()
        authorisation = call(
            "POST",
            "/v1/me/profile/photo-upload",
            body={
                "contentType": "image/png",
                "sizeBytes": len(photo),
                "sha256": hashlib.sha256(photo).hexdigest(),
            },
            expected=201,
        )
        try:
            upload_id = str(UUID(authorisation["uploadId"]))
            upload_url = authorisation["uploadUrl"]
            required_headers = authorisation["requiredHeaders"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SafeTestFailure("Upload authorisation was not usable") from exc
        if (
            authorisation.get("method") != "PUT"
            or not isinstance(upload_url, str)
            or not upload_url.startswith("https://storage.googleapis.com/")
            or required_headers != {"Content-Length": str(len(photo)), "Content-Type": "image/png"}
        ):
            raise SafeTestFailure("Upload authorisation did not use the approved restrictions")
        checks.append("short_lived_restricted_upload_authorised")

        try:
            uploaded = requests.put(
                upload_url,
                data=photo,
                headers=required_headers,
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SafeTestFailure("Synthetic photo could not reach private storage") from exc
        if uploaded.status_code not in {200, 201}:
            raise SafeTestFailure("Synthetic photo upload was not accepted")
        checks.append("synthetic_photo_uploaded_directly_to_private_storage")

        completed = call("POST", f"/v1/me/profile/photo-upload/{upload_id}/complete")
        if completed.get("id") != session["user"]["id"] or not completed.get("photoUrl"):
            raise SafeTestFailure("Sanitised photo was not attached to the same Member")

        try:
            viewed = requests.get(completed["photoUrl"], timeout=30, allow_redirects=False)
        except requests.RequestException as exc:
            raise SafeTestFailure("Sanitised profile photo could not be read") from exc
        if viewed.status_code != 200 or viewed.headers.get("Content-Type") != "image/webp":
            raise SafeTestFailure("Profile did not return the approved WebP photo")
        try:
            with Image.open(io.BytesIO(viewed.content)) as clean:
                clean.load()
                if clean.format != "WEBP" or clean.size != (48, 36) or clean.getexif():
                    raise SafeTestFailure("Approved photo was not sanitised as expected")
                if any(key.lower() in {"comment", "exif", "xmp"} for key in clean.info):
                    raise SafeTestFailure("Approved photo retained source metadata")
        except (OSError, ValueError) as exc:
            raise SafeTestFailure("Approved profile photo was not a valid image") from exc
        checks.append("photo_converted_to_metadata_free_webp")

        reread = call("GET", "/v1/me/profile")
        if reread.get("id") != session["user"]["id"] or not reread.get("photoUrl"):
            raise SafeTestFailure("Profile did not return its short-lived photo link")
        call("POST", f"/v1/me/profile/photo-upload/{upload_id}/complete", expected=409)
        checks.append("profile_read_succeeded_and_completed_upload_reuse_was_rejected")
        return checks
    finally:
        if access:
            call("POST", "/v1/auth/logout", expected=204)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-013-PHOTO-development"])
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
        checks = check_profile_photo(
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
                    "synthetic_photo_retained": True,
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
