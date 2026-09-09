from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ConfigurationError, Settings, load_settings, parse_env_text

PARITY_FIXTURE = Path(__file__).parent / "fixtures" / "config-parity.json"
PARITY_DATA = json.loads(PARITY_FIXTURE.read_text(encoding="utf-8"))


def base_environment(settings) -> dict[str, str]:
    return {
        f"EE_{name.upper()}": str(value).lower() if isinstance(value, bool) else str(value)
        for name, value in settings.model_dump().items()
    }


def secure_values(settings) -> dict:
    values = settings.model_dump()
    values.update(
        environment="staging",
        app_name="Elder Engage",
        gcp_project_id="client-staging-project",
        gcp_region="asia-south1",
        public_api_origin="https://api.staging.client.invalid",
        trusted_hosts="api.staging.client.invalid",
        cors_origins="https://admin.staging.client.invalid",
        cloud_sql_instance="client-staging-project:asia-south1:engagement-postgres",
        rate_limit_store="redis",
        member_identity_provider="firebase",
        firebase_project_id="client-staging-project",
        member_token_audience="client-staging-project",  # noqa: S106 - public audience ID
        uploads_bucket="client-staging-quarantine",
        approved_media_bucket="client-staging-approved",
        upload_signer_service_account=(
            "ee-upload-signer@client-staging-project.iam.gserviceaccount.com"
        ),
    )
    for name, value in list(values.items()):
        if name.endswith("_secret_ref") and value:
            secret_name = name.removesuffix("_secret_ref").replace("_", "-")
            values[name] = f"projects/client-staging-project/secrets/{secret_name}/versions/1"
    values["redis_url_secret_ref"] = (
        "projects/client-staging-project/secrets/redis-url/versions/1"  # noqa: S105 - resource name
    )
    return values


def test_checked_in_engagement_example_loads(settings):
    assert settings.environment == "development"
    assert settings.api_prefix == "/v1"
    assert settings.member_identity_provider == "mock"


def test_unknown_engagement_setting_fails(settings):
    environment = {**base_environment(settings), "EE_DATABASE_PASSWORD": "not-real"}
    with pytest.raises(ConfigurationError, match="unknown engagement configuration"):
        load_settings(environment)


def test_secure_environment_rejects_local_placeholder_configuration(settings):
    environment = {**base_environment(settings), "EE_ENVIRONMENT": "staging"}
    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        load_settings(environment)


def test_raw_secret_value_is_rejected(settings):
    environment = {
        **base_environment(settings),
        "EE_DATABASE_URL_SECRET_REF": "postgresql://user:password@host/database",
    }
    with pytest.raises(ConfigurationError, match="configuration is invalid") as captured:
        load_settings(environment)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "field",
    [key.removeprefix("EE_").lower() for key in PARITY_DATA["requiredCoreSecretRefs"]],
)
def test_core_secret_references_cannot_be_empty(settings, field):
    values = settings.model_dump()
    values[field] = ""
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_shared_python_js_config_parity_fixtures():
    for case in PARITY_DATA["cases"]:
        environment = parse_env_text(case["env"])
        if case["valid"]:
            assert load_settings(environment)
        else:
            with pytest.raises(ConfigurationError):
                load_settings(environment)


def test_runtime_environment_loader_uses_process_environment(settings, monkeypatch):
    for key in [key for key in os.environ if key.startswith("EE_")]:
        monkeypatch.delenv(key)
    for key, value in base_environment(settings).items():
        monkeypatch.setenv(key, value)
    assert load_settings().app_name == settings.app_name


def test_env_parser_rejects_malformed_and_duplicate_lines():
    with pytest.raises(ConfigurationError, match="expected KEY=VALUE"):
        parse_env_text("NOT_AN_ASSIGNMENT")
    with pytest.raises(ConfigurationError, match="duplicate key"):
        parse_env_text("EE_ENVIRONMENT=development\nEE_ENVIRONMENT=production")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"upload_signer_service_account": "not-an-account"}, "service-account email"),
        (
            {"database_url_secret_ref": "projects/other-project/secrets/database/versions/1"},
            "environment project",
        ),
        ({"approved_media_bucket": "client-staging-quarantine"}, "must be distinct"),
        ({"redis_url_secret_ref": ""}, "Redis mode requires"),
        ({"firebase_project_id": ""}, "identity provider requires"),
        ({"fcm_enabled": True, "fcm_project_id": ""}, "enabled FCM"),
        ({"youtube_enabled": True, "youtube_api_key_secret_ref": ""}, "enabled YouTube"),
        ({"meet_mode": "api", "meet_oauth_client_secret_ref": ""}, "Meet API mode"),
        ({"broadcast_provider": "agora", "agora_app_id": ""}, "Agora mode requires"),
    ],
)
def test_cross_field_contract_rejects_incomplete_modes(settings, changes, message):
    values = {**secure_values(settings), **changes}
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"public_api_origin": "http://api.staging.client.invalid"}, "HTTPS origin"),
        ({"public_api_origin": "https://api.staging.client.invalid/v1"}, "without a path"),
        ({"cors_origins": "http://admin.staging.client.invalid"}, "HTTPS origins"),
        ({"cors_origins": "https://admin.staging.client.invalid/path"}, "without paths"),
        ({"trusted_hosts": "*"}, "wildcard host or origin"),
        ({"trusted_hosts": "https://api.staging.client.invalid"}, "host names only"),
        ({"trusted_hosts": "other.staging.client.invalid"}, "must appear in TRUSTED_HOSTS"),
        ({"member_identity_provider": "mock"}, "mock identity"),
        ({"rate_limit_store": "memory"}, "memory rate limiting"),
    ],
)
def test_secure_environment_rules_fail_closed(settings, changes, message):
    values = {**secure_values(settings), **changes}
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(values)


def test_production_pins_secret_versions(settings):
    values = secure_values(settings)
    values["environment"] = "production"
    values["database_url_secret_ref"] = (
        "projects/client-staging-project/secrets/database-url/versions/latest"  # noqa: S105
    )
    with pytest.raises(ValidationError, match="pin a numeric secret version"):
        Settings.model_validate(values)
