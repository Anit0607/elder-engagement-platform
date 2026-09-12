from __future__ import annotations

import base64
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from google.cloud.sql.connector import IPTypes

from app.config import ConfigurationError, Settings
from app.main import create_app
from app.member_auth import MemberSessionService, UnconfiguredMemberSessionService
from app.member_runtime import _session_secret, member_runtime


def connected_settings(settings):
    values = settings.model_dump()
    values.update(
        member_session_enabled=True,
        member_identity_provider="identity_platform",
        firebase_project_id=settings.gcp_project_id,
        member_token_audience=settings.gcp_project_id,
        database_iam_user="synthetic-runtime@example-development-project.iam",
        public_api_origin="https://api.synthetic.example",
    )
    return Settings.model_validate(values)


def secret_environment():
    return {
        "AMIKO_SESSION_SIGNING_KEY_BASE64": base64.b64encode(b"a" * 48).decode(),
        "AMIKO_REFRESH_PEPPER_BASE64": base64.b64encode(b"b" * 48).decode(),
    }


class FakeConnector:
    def __init__(self, **options):
        self.options = options
        self.closed = False
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.closed = True

    async def connect_async(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


@pytest.mark.anyio
async def test_member_runtime_uses_private_iam_connection_and_closes_resources(settings):
    connector = FakeConnector()
    captured = {}

    def connector_factory(**options):
        connector.options = options
        return connector

    @asynccontextmanager
    async def pool_factory(instance, **options):
        captured.update(options)
        await options["connect"](instance, command_timeout=5)
        try:
            yield object()
        finally:
            captured["closed"] = True

    async with member_runtime(
        connected_settings(settings),
        environ=secret_environment(),
        connector_factory=connector_factory,
        pool_factory=pool_factory,
    ) as handler:
        assert isinstance(handler, MemberSessionService)
        assert connector.options["ip_type"] == IPTypes.PRIVATE
        assert connector.options["enable_iam_auth"] is True
        assert captured["max_size"] == 4
        assert "password" not in connector.calls[0][1]
        assert connector.calls[0][1]["db"] == "engagement"
    assert connector.closed is True
    assert captured["closed"] is True


@pytest.mark.parametrize("value", ["", "not-base64!", base64.b64encode(b"short").decode()])
def test_session_secret_injection_fails_closed_without_exposing_value(value):
    with pytest.raises(ConfigurationError) as captured:
        _session_secret({"synthetic": value}, "synthetic")
    assert value == "" or value not in str(captured.value)


def test_live_member_settings_cannot_use_mock_or_wrong_project(settings):
    values = connected_settings(settings).model_dump()
    for changes in [
        {"member_identity_provider": "mock"},
        {"database_iam_user": ""},
        {"firebase_project_id": "wrong-project"},
        {"cloud_sql_instance": "wrong-project:asia-south1:synthetic"},
    ]:
        with pytest.raises(ValueError):
            Settings.model_validate({**values, **changes})


def test_application_lifespan_connects_and_releases_runtime(settings):
    lifecycle = []

    @asynccontextmanager
    async def factory(config):
        assert config.member_session_enabled is True
        lifecycle.append("connected")
        try:
            yield UnconfiguredMemberSessionService()
        finally:
            lifecycle.append("closed")

    app = create_app(connected_settings(settings), member_runtime_factory=factory)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert lifecycle == ["connected"]
    assert lifecycle == ["connected", "closed"]
