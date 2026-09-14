from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.account_controls import (
    PostgresAccountControls,
    RoleChangeRequest,
    StatusChangeRequest,
    UnconfiguredAccountControls,
)
from app.authorization import Permission, Principal
from app.config import Settings
from app.main import create_app
from app.member_auth import MemberSessionFailure
from app.member_runtime import member_runtime
from tests.test_member_runtime import FakeConnector, secret_environment
from tests.test_shared_staff_runtime import staff_settings


@pytest.mark.parametrize("model", [StatusChangeRequest, RoleChangeRequest])
@pytest.mark.parametrize("reason", ["", "  ", "ab", "x" * 501, None, 123])
def test_change_reason_is_required_and_validated(model, reason):
    key = "role" if model is RoleChangeRequest else "status"
    with pytest.raises(ValidationError):
        model.model_validate({key: "active" if key == "status" else "member", "reason": reason})


class Authorization:
    def __init__(self):
        self.actor, self.target = uuid4(), uuid4()
        self.row = dict(
            id=self.target,
            role="member",
            status="active",
            phone_e164="synthetic-phone",
            identity_provider_subject="synthetic-subject",
        )
        self.credential = dict(
            second_factor_enabled=True, mfa_secret_ciphertext=bytes(60), last_accepted_totp_step=100
        )
        self.count = 2
        self.calls = []
        self.committed = False
        self.execute = AsyncMock(side_effect=lambda *args: self.calls.append(args))
        self.fetchval = AsyncMock(side_effect=lambda *args: self.count)

    @asynccontextmanager
    async def transaction(self, token, permission, *, target):
        assert permission in {Permission.ACCOUNT_STATUS, Permission.ACCOUNT_ROLE}
        assert target == self.target
        yield self, Principal(self.actor, uuid4(), "administrator")
        self.committed = True

    async def fetchrow(self, query, *args):
        if "staff_credentials" in query:
            return self.credential
        if "LEFT JOIN" in query:
            return dict(
                id=self.target,
                role=self.row["role"],
                status=self.row["status"],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                display_name=None,
                preferred_language=None,
                profile_complete=False,
            )
        return self.row


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["active", "suspended"])
async def test_status_change_and_safe_audit(status):
    auth = Authorization()
    await PostgresAccountControls(auth).status(
        "synthetic",
        auth.target,
        StatusChangeRequest(status=status, reason="Synthetic approved reason"),
        "synthetic-trace",
    )
    assert auth.committed
    assert any("audit_events" in call[0] for call in auth.calls)
    assert any("revoked_at=now()" in call[0] for call in auth.calls) == (status == "suspended")
    assert "synthetic-phone" not in auth.calls[-1][-1]


@pytest.mark.anyio
@pytest.mark.parametrize("state", [None, "invited", "deleted"])
async def test_unavailable_or_unactivated_target_is_not_changed(state):
    auth = Authorization()
    if state is None:
        auth.row = None
    else:
        auth.row["status"] = state
    with pytest.raises(MemberSessionFailure) as error:
        await PostgresAccountControls(auth).status(
            "synthetic", auth.target, StatusChangeRequest(status="active", reason="Synthetic reason"), "trace"
        )
    assert error.value.status == (404 if state is None else 409)
    assert not auth.calls and not auth.committed


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["suspend", "demote"])
async def test_last_administrator_is_protected(operation):
    auth = Authorization()
    auth.row["role"] = "administrator"
    auth.count = 1
    controls = PostgresAccountControls(auth)
    with pytest.raises(MemberSessionFailure) as error:
        if operation == "suspend":
            await controls.status(
                "synthetic",
                auth.target,
                StatusChangeRequest(status="suspended", reason="Synthetic reason"),
                "trace",
            )
        else:
            await controls.role(
                "synthetic",
                auth.target,
                RoleChangeRequest(role="contributor", reason="Synthetic reason"),
                "trace",
            )
    assert error.value.status == 409 and not auth.calls


@pytest.mark.anyio
async def test_member_to_contributor_invites_and_revokes_old_sessions():
    auth = Authorization()
    await PostgresAccountControls(auth).role(
        "synthetic", auth.target, RoleChangeRequest(role="contributor", reason="Synthetic reason"), "trace"
    )
    assert auth.calls[0][1:] == (auth.target, "contributor", "invited")
    assert "revoked_at" in auth.calls[1][0]


@pytest.mark.anyio
@pytest.mark.parametrize("credential", [None, "disabled", "missing-seed", "unconfirmed"])
async def test_unconfirmed_administrator_promotion_is_refused(credential):
    auth = Authorization()
    auth.row["role"] = "contributor"
    if credential is None:
        auth.credential = None
    elif credential == "disabled":
        auth.credential["second_factor_enabled"] = False
    elif credential == "missing-seed":
        auth.credential["mfa_secret_ciphertext"] = None
    else:
        auth.credential["last_accepted_totp_step"] = None
    with pytest.raises(MemberSessionFailure):
        await PostgresAccountControls(auth).role(
            "synthetic",
            auth.target,
            RoleChangeRequest(role="administrator", reason="Synthetic reason"),
            "trace",
        )
    assert not auth.calls


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["administrator", "member", "contributor"])
async def test_valid_role_changes_and_same_role_audit(role):
    auth = Authorization()
    auth.row["role"] = "contributor"
    await PostgresAccountControls(auth).role(
        "synthetic", auth.target, RoleChangeRequest(role=role, reason="Synthetic reason"), "trace"
    )
    assert auth.committed and "audit_events" in auth.calls[-1][0]
    if role == "member":
        assert "DELETE FROM engagement_app.staff_credentials" in auth.calls[0][0]
    if role == "contributor":
        assert len(auth.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["phone_e164", "identity_provider_subject"])
async def test_staff_cannot_become_member_without_google_phone_identity(missing):
    auth = Authorization()
    auth.row["role"] = "contributor"
    auth.row[missing] = None
    with pytest.raises(MemberSessionFailure):
        await PostgresAccountControls(auth).role(
            "synthetic", auth.target, RoleChangeRequest(role="member", reason="Synthetic reason"), "trace"
        )
    assert not auth.calls


@pytest.mark.anyio
async def test_audit_failure_does_not_report_commit():
    auth = Authorization()
    auth.execute.side_effect = OSError("Synthetic failure")
    with pytest.raises(OSError):
        await PostgresAccountControls(auth).status(
            "synthetic",
            auth.target,
            StatusChangeRequest(status="suspended", reason="Synthetic reason"),
            "trace",
        )
    assert not auth.committed


@pytest.mark.parametrize("value", ["yes", "", [], {}])
def test_invalid_account_control_switch(settings, value):
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "account_controls_enabled": value})


def test_account_controls_require_live_staff(settings):
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "account_controls_enabled": True})


@pytest.mark.anyio
async def test_account_runtime_wires_authorizer_with_staff(settings):
    config = Settings.model_validate(
        {**staff_settings(settings).model_dump(), "account_controls_enabled": True}
    )
    pool = Mock()
    pool.fetchval = AsyncMock(return_value=True)

    @asynccontextmanager
    async def acquire():
        yield pool

    pool.acquire = acquire

    @asynccontextmanager
    async def pool_factory(*args, **kwargs):
        yield pool

    env = secret_environment()
    env["AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"] = base64.b64encode(b"c" * 32).decode()
    async with member_runtime(
        config, environ=env, connector_factory=FakeConnector, pool_factory=pool_factory
    ) as handler:
        assert isinstance(handler.account_controls, PostgresAccountControls)
        assert handler.account_controls._authorization._staff is not None


def test_account_lifespan_wires_and_resets_handler(settings):
    config = Settings.model_validate(
        {**staff_settings(settings).model_dump(), "account_controls_enabled": True}
    )
    controls = Mock()

    @asynccontextmanager
    async def factory(_):
        yield Mock(session_controls=Mock(), account_controls=controls)

    app = create_app(config, member_runtime_factory=factory)
    with TestClient(app):
        assert app.state.account_controls is controls
    assert isinstance(app.state.account_controls, UnconfiguredAccountControls)


@pytest.mark.parametrize("action", ["status", "role"])
def test_account_http_boundary_authorization_validation_and_disabled_default(settings, action):
    auth = Authorization()
    controls = PostgresAccountControls(auth)
    path = f"/v1/admin/users/{auth.target}/{action}"
    payload = {action: "suspended" if action == "status" else "contributor", "reason": "Synthetic reason"}
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, account_controls=controls)) as client:
        assert client.patch(path, json=payload).status_code == 401
        assert client.patch(path, json={**payload, "unsafeExtra": True}, headers=headers).status_code == 400
        assert client.patch(path, json=payload, headers=headers).status_code == 200
        for code in [401, 403, 404, 409, 503]:
            getattr(controls, action)  # confirm the actual method, not a posted role
            setattr(
                controls,
                action,
                AsyncMock(side_effect=MemberSessionFailure(status=code, code="SYNTHETIC", title="Denied")),
            )
            assert client.patch(path, json=payload, headers=headers).status_code == code
    with TestClient(create_app(settings)) as client:
        assert client.patch(path, json=payload, headers=headers).status_code == 503
