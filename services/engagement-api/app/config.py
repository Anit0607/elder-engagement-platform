from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SECRET_REF_PATTERN = re.compile(
    r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}/versions/(?:latest|[1-9][0-9]*)$"
)
SERVICE_ACCOUNT_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$"
)


class ConfigurationError(RuntimeError):
    """Raised when runtime configuration is incomplete or unsafe."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "staging", "production"]
    app_name: str = Field(min_length=1, max_length=100)
    api_prefix: Literal["/v1"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]

    gcp_project_id: str = Field(min_length=1)
    gcp_region: str = Field(min_length=1)
    public_api_origin: str = Field(min_length=1)
    trusted_hosts: str = Field(min_length=1)
    cors_origins: str = Field(min_length=1)

    cloud_sql_instance: str = Field(min_length=1)
    database_url_secret_ref: str = Field(min_length=1)
    rate_limit_store: Literal["memory", "redis"]
    redis_url_secret_ref: str = ""

    session_signing_key_secret_ref: str = Field(min_length=1)
    refresh_token_pepper_secret_ref: str = Field(min_length=1)
    field_encryption_key_secret_ref: str = Field(min_length=1)

    member_identity_provider: Literal["mock", "firebase", "identity_platform"]
    firebase_project_id: str = ""
    member_token_audience: str = ""
    member_session_enabled: bool = False
    staff_session_enabled: bool = False
    profile_enabled: bool = False
    profile_photo_enabled: bool = False
    content_upload_enabled: bool = False
    account_controls_enabled: bool = False
    staff_authenticator_key_secret_ref: str = ""
    database_iam_user: str = ""

    uploads_bucket: str = Field(min_length=1)
    approved_media_bucket: str = Field(min_length=1)
    upload_signer_service_account: str = Field(min_length=1)
    upload_max_bytes: int = Field(ge=32_768, le=1_073_741_824)
    upload_allowed_mime_types: str = Field(min_length=1)
    upload_authorization_seconds: int = Field(ge=60, le=900)

    fcm_enabled: bool
    fcm_project_id: str = ""
    youtube_enabled: bool
    youtube_api_key_secret_ref: str = ""
    meet_mode: Literal["disabled", "link", "api"]
    meet_oauth_client_secret_ref: str = ""
    broadcast_provider: Literal["disabled", "agora"]
    agora_app_id: str = ""
    agora_app_certificate_secret_ref: str = ""

    access_token_minutes: int = Field(ge=5, le=30)
    refresh_token_days: int = Field(ge=1, le=90)

    @property
    def trusted_host_list(self) -> list[str]:
        return [value.strip() for value in self.trusted_hosts.split(",") if value.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @field_validator(
        "database_url_secret_ref",
        "redis_url_secret_ref",
        "session_signing_key_secret_ref",
        "refresh_token_pepper_secret_ref",
        "field_encryption_key_secret_ref",
        "staff_authenticator_key_secret_ref",
        "youtube_api_key_secret_ref",
        "meet_oauth_client_secret_ref",
        "agora_app_certificate_secret_ref",
    )
    @classmethod
    def validate_secret_reference(cls, value: str) -> str:
        if value and not SECRET_REF_PATTERN.fullmatch(value):
            raise ValueError("credential settings must be Secret Manager version references")
        return value

    @field_validator("upload_signer_service_account")
    @classmethod
    def validate_signer(cls, value: str) -> str:
        if not SERVICE_ACCOUNT_PATTERN.fullmatch(value):
            raise ValueError("upload signer must be a service-account email")
        return value

    @field_validator(
        "staff_session_enabled",
        "profile_enabled",
        "profile_photo_enabled",
        "content_upload_enabled",
        "account_controls_enabled",
        mode="before",
    )
    @classmethod
    def strict_staff_switch(cls, value):
        if type(value) is bool or (isinstance(value, str) and value in {"true", "false"}):
            return value
        raise ValueError("Staff session switch must be true or false")

    @model_validator(mode="after")
    def validate_environment_contract(self) -> Settings:
        references = {
            name: value for name, value in self.model_dump().items() if name.endswith("_secret_ref") and value
        }
        for name, value in references.items():
            if value.split("/")[1] != self.gcp_project_id:
                raise ValueError(f"{name} must reference the configured environment project")

        if self.uploads_bucket == self.approved_media_bucket:
            raise ValueError("quarantine and approved-media buckets must be distinct")
        if self.rate_limit_store == "redis" and not self.redis_url_secret_ref:
            raise ValueError("Redis mode requires REDIS_URL_SECRET_REF")
        if self.member_identity_provider != "mock" and not (
            self.firebase_project_id and self.member_token_audience
        ):
            raise ValueError("selected member identity provider requires project and token audience")
        if self.member_session_enabled:
            if self.member_identity_provider == "mock":
                raise ValueError("live Member sessions require Google phone identity")
            if (
                self.firebase_project_id != self.gcp_project_id
                or self.member_token_audience != self.gcp_project_id
            ):
                raise ValueError("Member identity project and audience must match the environment")
            if not self.database_iam_user or any(character.isspace() for character in self.database_iam_user):
                raise ValueError("live Member sessions require the application IAM database user")
            if not self.cloud_sql_instance.startswith(f"{self.gcp_project_id}:{self.gcp_region}:"):
                raise ValueError("Cloud SQL must match the environment project and region")
        if self.staff_session_enabled:
            if not self.member_session_enabled:
                raise ValueError("Staff sessions require the connected shared identity runtime")
            ref = self.staff_authenticator_key_secret_ref
            other_refs = (
                self.session_signing_key_secret_ref,
                self.refresh_token_pepper_secret_ref,
                self.field_encryption_key_secret_ref,
            )
            if (
                not ref
                or ref.endswith("/latest")
                or any(ref.split("/versions/")[0] == other.split("/versions/")[0] for other in other_refs)
            ):
                raise ValueError("Staff authenticator requires a separate pinned secret")
        if self.profile_enabled and not self.member_session_enabled:
            raise ValueError("Profiles require the connected identity runtime")
        if self.profile_photo_enabled and not self.profile_enabled:
            raise ValueError("Profile photos require connected profiles")
        if self.content_upload_enabled and not self.staff_session_enabled:
            raise ValueError("Contributor content uploads require the connected staff runtime")
        if self.account_controls_enabled and not self.staff_session_enabled:
            raise ValueError("Account controls require the connected staff runtime")
        if self.fcm_enabled and not self.fcm_project_id:
            raise ValueError("enabled FCM requires FCM_PROJECT_ID")
        if self.youtube_enabled and not self.youtube_api_key_secret_ref:
            raise ValueError("enabled YouTube requires YOUTUBE_API_KEY_SECRET_REF")
        if self.meet_mode == "api" and not self.meet_oauth_client_secret_ref:
            raise ValueError("Meet API mode requires MEET_OAUTH_CLIENT_SECRET_REF")
        if self.broadcast_provider == "agora" and not (
            self.agora_app_id and self.agora_app_certificate_secret_ref
        ):
            raise ValueError("Agora mode requires app ID and certificate secret reference")

        if self.environment in {"staging", "production"}:
            serialized = "\n".join(str(value) for value in self.model_dump().values()).lower()
            forbidden = ["example", "replace", "pending", "localhost", "127.0.0.1"]
            found = next((marker for marker in forbidden if marker in serialized), None)
            if found:
                raise ValueError(f"secure environment contains forbidden marker: {found}")
            public_origin = urlsplit(self.public_api_origin)
            if (
                public_origin.scheme != "https"
                or not public_origin.hostname
                or public_origin.path not in {"", "/"}
                or public_origin.query
                or public_origin.fragment
                or public_origin.username
                or public_origin.password
            ):
                raise ValueError("secure environment API URL must be an HTTPS origin without a path")
            for origin in self.cors_origin_list:
                parsed = urlsplit(origin)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("secure environment CORS values must be HTTPS origins without paths")
            if "*" in self.trusted_host_list or "*" in self.cors_origin_list:
                raise ValueError("wildcard host or origin is forbidden")
            if any("://" in host or "/" in host or " " in host for host in self.trusted_host_list):
                raise ValueError("trusted hosts must contain host names only")
            if public_origin.hostname not in self.trusted_host_list:
                raise ValueError("public API host must appear in TRUSTED_HOSTS")
            if self.member_identity_provider == "mock":
                raise ValueError("mock identity is development-only")
            if self.rate_limit_store == "memory":
                raise ValueError("memory rate limiting is development-only")
        if self.environment == "production":
            latest = next((name for name, value in references.items() if value.endswith("/latest")), None)
            if latest:
                raise ValueError(f"production must pin a numeric secret version: {latest}")
        return self


ENV_TO_FIELD = {f"EE_{name.upper()}": name for name in Settings.model_fields}


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise ConfigurationError(f"line {line_number}: expected KEY=VALUE")
        if key in values:
            raise ConfigurationError(f"duplicate key: {key}")
        values[key] = value.strip()
    return values


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if environ is None else environ
    supplied = {key: value for key, value in source.items() if key.startswith("EE_")}
    unknown = sorted(set(supplied) - set(ENV_TO_FIELD))
    if unknown:
        raise ConfigurationError(f"unknown engagement configuration: {', '.join(unknown)}")
    payload = {ENV_TO_FIELD[key]: value for key, value in supplied.items()}
    try:
        return Settings.model_validate(payload)
    except ValidationError:
        raise ConfigurationError("engagement configuration is invalid") from None


def load_settings_file(path: Path) -> Settings:
    return load_settings(parse_env_text(path.read_text(encoding="utf-8")))
