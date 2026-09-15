from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.authorization import Permission, Principal, SessionAuthorization, require_permission
from app.member_auth import MemberSessionFailure
from tests.test_session_controls import NOW, SESSION, USER, FakePool, manager, proof
from tests.test_staff_session_controls import Pool, controls
from tests.test_staff_session_controls import proof as staff_proof


@pytest.mark.parametrize("role", ["member", "contributor", "administrator"])
@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("owned", [True, False])
def test_complete_permission_matrix(role, permission, owned):
    owner = uuid4()
    principal = Principal(owner, uuid4(), role)
    target = owner if owned else uuid4()
    own_permissions = {
        Permission.OWN_PROFILE,
        Permission.OWN_ACCOUNT,
        Permission.OWN_NOTIFICATIONS,
    }
    member_only_own = {
        Permission.VIEW_CIRCLES,
        Permission.OWN_CIRCLE_MEMBERSHIPS,
        Permission.VIEW_CONTENT_FEED,
        Permission.VIEW_EVENTS,
    }
    allowed = (
        owned
        if permission in own_permissions
        else role == "member" and owned
        if permission in member_only_own
        else role == "contributor" and owned
        if permission == Permission.UPLOAD_CONTENT
        else role == "administrator"
    )
    if allowed:
        require_permission(principal, permission, target)
    else:
        with pytest.raises(MemberSessionFailure) as error:
            require_permission(principal, permission, target)
        assert (error.value.status, error.value.code) == (403, "FORBIDDEN")


def test_unknown_permission_and_role_never_grant_access():
    owner = uuid4()
    for role, action in [("member", "unknown"), ("unknown", Permission.OWN_PROFILE)]:
        with pytest.raises(MemberSessionFailure):
            require_permission(Principal(owner, uuid4(), role), action, owner)


@pytest.mark.anyio
async def test_member_authorization_keeps_same_connection_and_lock_order():
    pool = FakePool()
    auth = SessionAuthorization(pool, manager(pool), now=lambda: NOW)
    async with auth.transaction(proof(), Permission.OWN_PROFILE, target=USER) as (connection, principal):
        assert connection is pool
        assert principal == Principal(USER, SESSION, "member")
        assert "app_users" in pool.calls[0][0] and "FOR UPDATE" in pool.calls[0][0]
        assert "auth_sessions" in pool.calls[1][0] and "FOR UPDATE" in pool.calls[1][0]


@pytest.mark.anyio
@pytest.mark.parametrize("state,status", [("suspended", 403), ("invited", 401), ("deleted", 401)])
async def test_inactive_member_cannot_enter_protected_work(state, status):
    pool = FakePool()
    pool.user["status"] = state
    auth = SessionAuthorization(pool, manager(pool), now=lambda: NOW)
    with pytest.raises(MemberSessionFailure) as error:
        async with auth.transaction(proof(), Permission.OWN_PROFILE, target=USER):
            pytest.fail("Unauthorized work was reached")
    assert error.value.status == status


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind", ["missing-user", "changed-role", "revoked-session", "outage", "denied-action"]
)
async def test_member_current_state_failures(kind):
    pool = FakePool()
    if kind == "missing-user":
        pool.user = None
    if kind == "changed-role":
        pool.user["role"] = "administrator"
    if kind == "revoked-session":
        pool.session = None
    if kind == "outage":
        pool.error = TimeoutError()
    auth = SessionAuthorization(pool, manager(pool), now=lambda: NOW)
    action = Permission.CREATE_STAFF if kind == "denied-action" else Permission.OWN_PROFILE
    with pytest.raises(MemberSessionFailure) as error:
        async with auth.transaction(proof(), action, target=USER):
            pytest.fail("Unauthorized work was reached")
    assert error.value.status == (503 if kind == "outage" else 403 if kind == "denied-action" else 401)


@pytest.mark.anyio
@pytest.mark.parametrize("change", [None, "role", "version", "missing-session"])
async def test_staff_authorization_reuses_current_credential_guard(change):
    pool = Pool()
    staff = controls(pool)
    member = Mock()
    member._claims.side_effect = MemberSessionFailure(
        status=401, code="AUTHENTICATION_FAILED", title="Denied"
    )
    auth = SessionAuthorization(pool, member, staff, now=lambda: NOW)
    user_id = pool.user["id"]
    if change == "role":
        pool.user["role"] = "administrator"
    if change == "version":
        pool.credential["credential_version"] = uuid4()
    if change == "missing-session":
        pool.session = None
    if change is None:
        async with auth.transaction(staff_proof(), Permission.OWN_PROFILE, target=user_id) as (_, principal):
            assert principal.role == "contributor"
    else:
        with pytest.raises(MemberSessionFailure):
            async with auth.transaction(staff_proof(), Permission.OWN_PROFILE, target=user_id):
                pytest.fail("Unauthorized work was reached")


@pytest.mark.anyio
async def test_invalid_proof_with_disabled_staff_never_opens_database():
    pool = FakePool()
    with pytest.raises(MemberSessionFailure):
        async with SessionAuthorization(pool, manager(pool)).transaction("invalid", Permission.CREATE_STAFF):
            pytest.fail("Unauthorized work was reached")
    assert pool.calls == []


@pytest.mark.anyio
async def test_naive_clock_refused():
    pool = FakePool()
    auth = SessionAuthorization(pool, manager(pool), now=datetime.now)
    with pytest.raises(ValueError):
        async with auth.transaction(proof(), Permission.OWN_PROFILE, target=USER):
            pytest.fail("Naive clock was accepted")
