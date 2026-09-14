from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigurationError, Settings
from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.member_runtime import member_runtime
from app.shared_session_controls import SharedSessionControls
from app.staff_auth import UnconfiguredStaffSessionService
from app.staff_schema import verify_staff_schema
from tests.test_member_runtime import FakeConnector, connected_settings, secret_environment
from tests.test_staff_session_controls import NOW, REFRESH, Pool


def staff_settings(settings):
    values = connected_settings(settings).model_dump()
    values.update(
        staff_session_enabled=True,
        staff_authenticator_key_secret_ref=f"projects/{settings.gcp_project_id}/secrets/staff-auth/versions/1",
    )
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    "changes",
    [
        {"member_session_enabled": False},
        {"staff_authenticator_key_secret_ref": ""},
        {
            "staff_authenticator_key_secret_ref": (
                "projects/example-development-project/secrets/staff-auth/versions/latest"
            )
        },
        {
            "staff_authenticator_key_secret_ref": (
                "projects/example-development-project/secrets/ee-field-encryption-key/versions/1"
            )
        },
        {"staff_session_enabled": "yes"},
        {"staff_session_enabled": ""},
        {"staff_session_enabled": []},
        {"staff_session_enabled": {}},
    ],
)
def test_unsafe_staff_settings_rejected(settings, changes):
    with pytest.raises(ValueError):
        Settings.model_validate({**staff_settings(settings).model_dump(), **changes})


@pytest.mark.anyio
@pytest.mark.parametrize("material", [b"a" * 48, b"c" * 31, b"c" * 33, b"a" * 32, b"b" * 32])
async def test_bad_or_missing_staff_secret_fails_closed(settings, material):
    env = secret_environment()
    if material in {b"a" * 32, b"b" * 32}:
        env["AMIKO_SESSION_SIGNING_KEY_BASE64"] = base64.b64encode(b"a" * 32).decode()
        env["AMIKO_REFRESH_PEPPER_BASE64"] = base64.b64encode(b"b" * 32).decode()
    env["AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"] = base64.b64encode(material).decode()
    with pytest.raises(ConfigurationError):
        async with member_runtime(staff_settings(settings), environ=env):
            pytest.fail("Unsafe key reached live runtime")


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "not-base64!"])
async def test_missing_or_malformed_staff_secret_is_rejected(settings, value):
    env = secret_environment()
    if value is not None:
        env["AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"] = value
    with pytest.raises(ConfigurationError):
        async with member_runtime(staff_settings(settings), environ=env):
            pytest.fail("Missing key reached live runtime")


@pytest.mark.anyio
async def test_invalid_access_never_calls_any_session_operation():
    member, staff = Mock(), Mock()
    for adapter in (member, staff):
        adapter._claims.side_effect = MemberSessionFailure(
            status=401, code="AUTHENTICATION_FAILED", title="Denied"
        )
        adapter.list_sessions = AsyncMock()
    with pytest.raises(MemberSessionFailure):
        await SharedSessionControls(Pool(), member, staff, b"c" * 32).list_sessions("invalid")
    member.list_sessions.assert_not_awaited()
    staff.list_sessions.assert_not_awaited()


@pytest.mark.anyio
async def test_staff_runtime_wires_shared_handlers_and_checks_schema(settings):
    env = secret_environment()
    env["AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"] = base64.b64encode(b"c" * 32).decode()
    pool = Pool()
    pool.fetchval = AsyncMock(return_value=True)

    @asynccontextmanager
    async def pool_factory(*args, **kwargs):
        yield pool

    async with member_runtime(
        staff_settings(settings), environ=env, connector_factory=FakeConnector, pool_factory=pool_factory
    ) as handler:
        assert isinstance(handler.session_controls, SharedSessionControls)
        assert not isinstance(handler.staff_session_handler, UnconfiguredStaffSessionService)
        pool.fetchval.assert_awaited_once()
        assert "engagement_migrations" not in pool.fetchval.call_args.args[0]


@pytest.mark.anyio
@pytest.mark.parametrize("ready", [False, None, 1])
async def test_schema_readiness_requires_boolean_true(ready):
    pool = Pool()
    pool.fetchval = AsyncMock(return_value=ready)
    with pytest.raises(ConfigurationError):
        await verify_staff_schema(pool)


def test_lifespan_connects_and_resets_staff_handler(settings):
    staff = Mock()

    @asynccontextmanager
    async def factory(config):
        yield Mock(session_controls=Mock(), staff_session_handler=staff)

    app = create_app(staff_settings(settings), member_runtime_factory=factory)
    with TestClient(app):
        assert app.state.staff_session_handler is staff
    assert isinstance(app.state.staff_session_handler, UnconfiguredStaffSessionService)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["member", "staff"])
@pytest.mark.parametrize("action", ["list", "logout", "revoke"])
async def test_access_dispatch_requires_verified_claims(kind, action):
    member, staff = Mock(), Mock()
    if kind == "staff":
        member._claims.side_effect = MemberSessionFailure(
            status=401, code="AUTHENTICATION_FAILED", title="Denied"
        )
    for adapter in (member, staff):
        adapter.list_sessions = AsyncMock(return_value=[])
        adapter.logout = AsyncMock()
        adapter.revoke = AsyncMock()
    shared = SharedSessionControls(Pool(), member, staff, b"c" * 32)
    selected = member if kind == "member" else staff
    if action == "list":
        await shared.list_sessions("synthetic")
    elif action == "logout":
        await shared.logout("synthetic")
    else:
        await shared.revoke("synthetic", uuid4())
    selected._claims.assert_called_once()
    getattr(selected, {"list": "list_sessions"}.get(action, action)).assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("version", [None, uuid4()])
async def test_refresh_dispatch_uses_stored_marker(version):
    pool = Pool()
    pool.fetchrow = AsyncMock(return_value={"staff_credential_version": version})
    member, staff = Mock(), Mock()
    member.refresh = AsyncMock(return_value="member")
    staff.refresh = AsyncMock(return_value="staff")
    result = await SharedSessionControls(pool, member, staff, b"c" * 32).refresh(REFRESH)
    assert result == ("member" if version is None else "staff")


@pytest.mark.anyio
@pytest.mark.parametrize("token", [None, "invalid"])
async def test_bad_refresh_never_dispatches(token):
    with pytest.raises(MemberSessionFailure):
        await SharedSessionControls(Pool(), Mock(), Mock(), b"c" * 32).refresh(token)


@pytest.mark.anyio
async def test_unknown_refresh_or_database_outage_fails_closed():
    pool = Pool()
    pool.fetchrow = AsyncMock(return_value=None)
    shared = SharedSessionControls(pool, Mock(), Mock(), b"c" * 32)
    with pytest.raises(MemberSessionFailure) as error:
        await shared.refresh(REFRESH)
    assert error.value.status == 401
    pool.error = TimeoutError()
    with pytest.raises(MemberSessionFailure) as error:
        await shared.refresh(REFRESH)
    assert (error.value.status, error.value.retryable) == (503, False)


def test_shared_refresh_response_is_not_filtered_to_member(settings):
    from app.staff_auth import StaffSessionResponse, StaffUserSummary

    response = StaffSessionResponse(
        access_token="synthetic-access",  # noqa: S106 -- fictional response fixture
        refresh_token="synthetic-refresh",  # noqa: S106 -- fictional response fixture
        expires_in_seconds=600,
        user=StaffUserSummary(
            id=uuid4(),
            role="administrator",
            status="active",
            profile_complete=False,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
    handler = Mock(refresh=AsyncMock(return_value=response))
    with TestClient(create_app(settings, session_controls_handler=handler)) as client:
        result = client.post(
            "/v1/auth/refresh", json={"refreshToken": "synthetic-refresh-credential-long-enough"}
        )
        assert result.status_code == 200
        assert result.json()["user"]["role"] == "administrator"
