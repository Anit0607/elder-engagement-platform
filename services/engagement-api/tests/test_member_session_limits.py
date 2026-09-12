from __future__ import annotations

from uuid import uuid4

import pytest

from app.member_auth import MemberSessionFailure
from app.postgres_session_issuer import PostgresSessionIssuer
from tests.test_postgres_session_issuer import REFRESH_PEPPER, SIGNING_KEY, member
from tests.test_session_controls import FakePool


def limited(pool, count=5):
    return PostgresSessionIssuer(pool, signing_key=SIGNING_KEY, refresh_pepper=REFRESH_PEPPER,
                                 issuer="https://api.synthetic.example", member_session_limit=count)


@pytest.mark.anyio
@pytest.mark.parametrize("count,status", [(4, 200), (5, 429), (6, 429)])
async def test_recent_session_limit_is_server_side_and_user_scoped(count, status):
    pool = FakePool()

    async def recent(query, *args):
        assert "user_id=$1" in query
        assert "revoked_at" not in query  # Logout must not bypass the creation limit.
        assert args[0] == member().id
        return count

    pool.fetchval = recent
    if status == 200:
        response = await limited(pool).issue(member(), uuid4(), "android", None)
        assert response.access_token
    else:
        with pytest.raises(MemberSessionFailure) as result:
            await limited(pool).issue(member(), uuid4(), "android", None)
        assert result.value.status == status
        assert result.value.code == "RATE_LIMITED"
        assert not any("INSERT" in call[0] for call in pool.calls)


@pytest.mark.anyio
@pytest.mark.parametrize("user", [None, {"role": "contributor", "status": "active"},
                                  {"role": "member", "status": "suspended"}])
async def test_account_must_still_be_active_under_lock(user):
    pool = FakePool()
    pool.user = user
    with pytest.raises(MemberSessionFailure) as result:
        await limited(pool).issue(member(), uuid4(), "android", None)
    assert result.value.status == 401


def test_session_limit_configuration_is_bounded():
    for count in [-1, 21]:
        with pytest.raises(ValueError):
            limited(FakePool(), count)
