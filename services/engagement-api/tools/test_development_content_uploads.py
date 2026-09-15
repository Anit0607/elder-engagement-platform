"""Live development proof for private Contributor content uploads.

Uses the approved synthetic MP4, MP3 and PDF samples only. Credentials,
tokens, identifiers and signed storage links are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

import requests

from app.development_staff_setup import FictionalSetupInput
from tools.test_development_member_login import ROOT, SafeTestFailure, cloud_cli, request_json

SAMPLES = (
    ("amiko-synthetic-upload-sample.mp4", "video/mp4", "Synthetic video upload check"),
    ("amiko-synthetic-upload-sample.mp3", "audio/mpeg", "Synthetic audio upload check"),
    ("amiko-synthetic-upload-sample.pdf", "application/pdf", "Synthetic PDF upload check"),
)


def private_inputs() -> FictionalSetupInput:
    path = ROOT / "secure-runtime" / "fictional-staff-private" / "setup-input.json"
    try:
        resolved = path.resolve(strict=True)
        private_root = (ROOT / "secure-runtime" / "fictional-staff-private").resolve(strict=True)
        resolved.relative_to(private_root)
        return FictionalSetupInput.model_validate_json(resolved.read_text(encoding="utf-8"))
    except Exception:
        raise SafeTestFailure("Protected fictional Contributor inputs could not be read") from None


def sample_paths(sample_directory: Path) -> list[tuple[Path, str, str]]:
    try:
        resolved = sample_directory.resolve(strict=True)
        approved_root = (ROOT / "output" / "synthetic-media").resolve(strict=True)
        if resolved != approved_root:
            raise ValueError("unexpected sample directory")
        samples = [(resolved / name, content_type, title) for name, content_type, title in SAMPLES]
        if any(not path.is_file() for path, _, _ in samples):
            raise ValueError("missing synthetic sample")
        return samples
    except (OSError, ValueError):
        raise SafeTestFailure("The approved synthetic upload samples are not ready") from None


class ContentUploadProof:
    def __init__(self, origin: str, gateway: str, inputs: FictionalSetupInput):
        self.origin, self.gateway, self.inputs = origin, gateway, inputs
        self.access: str | None = None

    def call(self, method: str, path: str, *, body=None, expected=200):
        headers = {"X-Serverless-Authorization": f"Bearer {self.gateway}"}
        if self.access:
            headers["Authorization"] = f"Bearer {self.access}"
        safe_path = re.sub(
            r"/[0-9a-f]{8}-[0-9a-f-]{27,}", "/{identifier}", path, flags=re.IGNORECASE
        )
        try:
            status, payload = request_json(
                method, self.origin + path, headers=headers, json=body
            )
        except SafeTestFailure as error:
            raise SafeTestFailure(f"{method} {safe_path} could not reach the cloud service") from error
        if status != expected:
            raise SafeTestFailure(
                f"{method} {safe_path} returned {status}; expected {expected}"
            )
        return payload

    def sign_in(self) -> None:
        session = self.call(
            "POST",
            "/v1/auth/staff/session",
            body={
                "username": "fictional.ee010.contributor",
                "password": self.inputs.contributor_password.get_secret_value(),
                "installationId": str(uuid4()),
                "platform": "web",
            },
        )
        if session.get("user", {}).get("role") != "contributor" or not session.get(
            "accessToken"
        ):
            raise SafeTestFailure("Fictional Contributor sign-in did not return the expected role")
        self.access = session["accessToken"]

    def upload(self, path: Path, content_type: str, title: str) -> str:
        content = path.read_bytes()
        authorisation = self.call(
            "POST",
            "/v1/contributor/content-uploads",
            body={
                "title": title,
                "description": "Artificial Week 3 verification material; not for publication",
                "language": "en",
                "contentType": content_type,
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "rightsConfirmed": True,
            },
            expected=201,
        )
        try:
            upload_id = str(UUID(authorisation["uploadId"]))
            upload_url = authorisation["uploadUrl"]
            headers = authorisation["requiredHeaders"]
        except (KeyError, TypeError, ValueError) as error:
            raise SafeTestFailure("Upload authorisation was not usable") from error
        if (
            authorisation.get("method") != "PUT"
            or not isinstance(upload_url, str)
            or not upload_url.startswith("https://storage.googleapis.com/")
            or headers
            != {
                "Content-Length": str(len(content)),
                "Content-Type": content_type,
                "x-goog-if-generation-match": "0",
            }
        ):
            raise SafeTestFailure("Upload authorisation did not use the approved restrictions")
        try:
            uploaded = requests.put(
                upload_url,
                data=content,
                headers=headers,
                timeout=60,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise SafeTestFailure("Synthetic material could not reach private storage") from error
        if uploaded.status_code not in {200, 201}:
            raise SafeTestFailure("Private storage did not accept the synthetic material")
        receipt = self.call(
            "POST", f"/v1/contributor/content-uploads/{upload_id}/complete"
        )
        expected_kind = "pdf" if content_type == "application/pdf" else content_type.split("/")[0]
        if receipt.get("status") != "pending" or receipt.get("kind") != expected_kind:
            raise SafeTestFailure("Uploaded material was not placed in the private review queue")
        return expected_kind

    def run(self, samples: list[tuple[Path, str, str]]) -> list[str]:
        self.sign_in()
        try:
            completed = [self.upload(path, content_type, title) for path, content_type, title in samples]
            return [f"synthetic_{kind}_stored_private_and_pending_review" for kind in completed]
        finally:
            if self.access:
                try:
                    self.call("POST", "/v1/auth/logout", expected=204)
                except SafeTestFailure:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--sample-directory", type=Path, required=True)
    parser.add_argument("--confirm", required=True, choices=["TEST-EE-018-development"])
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
        checks = ContentUploadProof(
            origin, cloud_cli("auth", "print-identity-token"), private_inputs()
        ).run(sample_paths(arguments.sample_directory))
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "synthetic_material_only": True,
                    "material_publicly_visible": False,
                    "real_sms_sent": False,
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
