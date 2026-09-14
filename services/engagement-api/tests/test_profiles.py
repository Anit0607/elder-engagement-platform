from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authorization import Permission, Principal
from app.config import ConfigurationError, Settings
from app.main import create_app
from app.member_auth import MemberSessionFailure, UserSummary
from app.member_runtime import member_runtime
from app.postgres_profiles import PostgresProfileService, UnconfiguredProfileService, verify_profile_schema
from app.profiles import BroadLocation, NotificationWindow, ProfileUpdate
from app.staff_auth import StaffUserSummary
from tests.test_member_runtime import FakeConnector, connected_settings, secret_environment


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"displayName": None},
        {"displayName": " "},
        {"preferredLanguage": None},
        {"preferredLanguage": "xx"},
        {"interests": None},
        {"interests": ["x", "x"]},
        {"interests": [""]},
        {"interests": [" "]},
        {"interests": ["x" * 81]},
        {"interests": ["x"] * 31},
        {"notificationWindow": None},
        {"role": "administrator"},
        {"photoUrl": "https://synthetic.example/photo"},
        {"interests": [12]},
    ],
)
def test_invalid_profile_updates(values):
    with pytest.raises(ValidationError):
        ProfileUpdate.model_validate(values)


@pytest.mark.parametrize("language", ["bn", "hi", "en"])
def test_three_approved_languages_and_age_label(language):
    update = ProfileUpdate(displayName="Synthetic member", preferredLanguage=language, ageGroup="55+")
    assert update.age_group == "55+"
    # The label is not proof of age and is not an enforced minimum-age gate.
    assert ProfileUpdate(ageGroup=None).age_group is None


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": True, "timeZone": "UTC"},
        {"enabled": True, "timeZone": "UTC", "startLocalTime": "25:00", "endLocalTime": "09:00"},
        {"enabled": False, "timeZone": "UTC", "startLocalTime": "09:00"},
        {"enabled": "true", "timeZone": "UTC"},
        {"enabled": False, "timeZone": "not a timezone"},
    ],
)
def test_invalid_notification_windows(values):
    with pytest.raises(ValidationError):
        NotificationWindow.model_validate(values)


def test_midnight_window_and_nested_null_rules():
    assert NotificationWindow(
        enabled=True, timeZone="Asia/Kolkata", startLocalTime="22:00", endLocalTime="06:00"
    ).enabled
    assert BroadLocation(city="Synthetic city").country_code == "IN"
    with pytest.raises(ValidationError):
        BroadLocation(state=None)
    assert ProfileUpdate(broadLocation=None).broad_location is None


def test_session_summaries_accept_english():
    values = dict(
        id=uuid4(),
        status="active",
        profile_complete=True,
        preferred_language="en",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert UserSummary(role="member", **values).preferred_language == "en"
    assert StaffUserSummary(role="contributor", **values).preferred_language == "en"


class Authorization:
    def __init__(self):
        self.owner = uuid4()
        self.existing = None
        self.row = dict(
            id=self.owner,
            role="member",
            status="active",
            display_name="Synthetic member",
            preferred_language="en",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            age_group="55+",
            interests='["music"]',
            country_code=None,
            state_name=None,
            city_name=None,
            enabled=None,
            window_start=None,
            window_end=None,
            time_zone=None,
        )
        self.execute = AsyncMock()
        self.fetchval = AsyncMock(return_value=True)
        self.committed = False

    def _proof(self, token):
        return self.owner, uuid4(), "member", None

    @asynccontextmanager
    async def transaction(self, token, permission, *, target):
        assert permission == Permission.OWN_PROFILE and target == self.owner
        yield self, Principal(self.owner, uuid4(), "member")
        self.committed = True

    async def fetchrow(self, query, *args):
        return self.existing if "SELECT *" in query else self.row


@pytest.mark.anyio
async def test_get_profile_and_missing_profile():
    auth = Authorization()
    service = PostgresProfileService(auth)
    assert (await service.get("synthetic")).preferred_language == "en"
    auth.row = None
    with pytest.raises(MemberSessionFailure) as error:
        await service.get("synthetic")
    assert error.value.status == 404


@pytest.mark.anyio
async def test_create_profile_commits_fields_and_minimal_audit():
    auth = Authorization()
    request = ProfileUpdate(
        displayName="Synthetic member",
        preferredLanguage="en",
        ageGroup="55+",
        interests=["music"],
        broadLocation={"city": "Synthetic city"},
        notificationWindow={
            "enabled": True,
            "timeZone": "Asia/Kolkata",
            "startLocalTime": "22:00",
            "endLocalTime": "06:00",
        },
    )
    result = await PostgresProfileService(auth).update("synthetic", request, "synthetic-trace")
    assert result.id == auth.owner and auth.committed
    assert auth.execute.await_count == 3
    args = auth.execute.await_args_list[-1].args
    assert "Synthetic member" not in args[-1] and "Synthetic city" not in args[-1]
    assert '"created": true' in args[-1]


@pytest.mark.anyio
async def test_partial_update_preserves_omissions_and_clears_nullable_fields():
    auth = Authorization()
    auth.existing = dict(
        display_name="Original synthetic name",
        preferred_language="hi",
        age_group="55+",
        interests='["music"]',
        country_code="IN",
        state_name="Synthetic state",
        city_name="Synthetic city",
    )
    await PostgresProfileService(auth).update(
        "synthetic", ProfileUpdate(ageGroup=None, broadLocation=None), "trace"
    )
    args = auth.execute.await_args_list[0].args
    assert args[1:] == (auth.owner, "Original synthetic name", "hi", None, '["music"]', None, None, None)


@pytest.mark.anyio
async def test_create_missing_required_fields_and_unknown_zone_do_not_write():
    for request in [
        ProfileUpdate(ageGroup="55+"),
        ProfileUpdate(
            displayName="Synthetic",
            preferredLanguage="en",
            notificationWindow={"enabled": False, "timeZone": "Synthetic/Unknown"},
        ),
    ]:
        auth = Authorization()
        auth.fetchval.return_value = False
        with pytest.raises(MemberSessionFailure) as error:
            await PostgresProfileService(auth).update("synthetic", request, "trace")
        assert error.value.status == 400
        auth.execute.assert_not_awaited()
        assert not auth.committed


@pytest.mark.anyio
async def test_safe_location_time_response_and_invalid_stored_interests():
    auth = Authorization()
    auth.row.update(
        country_code="IN",
        state_name="Synthetic state",
        city_name="Synthetic city",
        enabled=True,
        window_start=time(22),
        window_end=time(6),
        time_zone="Asia/Kolkata",
        interests=["music"],
    )
    result = await PostgresProfileService(auth).get("synthetic")
    assert result.broad_location.city == "Synthetic city"
    assert result.notification_window.start_local_time == "22:00"
    auth.row["interests"] = "malformed-json"
    with pytest.raises(MemberSessionFailure) as error:
        await PostgresProfileService(auth).get("synthetic")
    assert error.value.status == 503


@pytest.mark.anyio
async def test_disabled_window_stores_no_local_times():
    auth = Authorization()
    await PostgresProfileService(auth).update(
        "synthetic",
        ProfileUpdate(
            displayName="Synthetic",
            preferredLanguage="hi",
            notificationWindow={"enabled": False, "timeZone": "UTC"},
        ),
        "trace",
    )
    assert auth.execute.await_args_list[1].args[1:] == (auth.owner, False, None, None, "UTC")


@pytest.mark.parametrize("value", ["yes", "", [], {}])
def test_invalid_profile_switch(settings, value):
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "profile_enabled": value})


def test_profile_runtime_requires_connected_identity(settings):
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "profile_enabled": True})


@pytest.mark.anyio
@pytest.mark.parametrize("ready", [True, False, None, 1])
async def test_profile_metadata_requires_boolean_true(ready):
    auth = Authorization()
    auth.fetchval.return_value = ready

    @asynccontextmanager
    async def acquire():
        yield auth

    auth.acquire = acquire
    if ready is True:
        await verify_profile_schema(auth)
    else:
        with pytest.raises(ConfigurationError):
            await verify_profile_schema(auth)


@pytest.mark.anyio
async def test_profile_runtime_wiring_without_staff(settings):
    config = Settings.model_validate({**connected_settings(settings).model_dump(), "profile_enabled": True})
    pool = Authorization()

    @asynccontextmanager
    async def acquire():
        yield pool

    pool.acquire = acquire

    @asynccontextmanager
    async def pool_factory(*args, **kwargs):
        yield pool

    async with member_runtime(
        config, environ=secret_environment(), connector_factory=FakeConnector, pool_factory=pool_factory
    ) as handler:
        assert isinstance(handler.profile_service, PostgresProfileService)
        assert handler.profile_service._authorization._staff is None


def test_http_profiles_validate_requests_hide_private_fields_and_remain_disabled_by_default(settings):
    auth = Authorization()
    service = PostgresProfileService(auth)
    headers = {"Authorization": "Bearer synthetic-proof"}
    with TestClient(create_app(settings, profile_service=service)) as client:
        result = client.get("/v1/me/profile", headers=headers)
        assert result.status_code == 200 and result.json()["preferredLanguage"] == "en"
        assert "photo_object_key" not in result.text
        assert client.get("/v1/me/profile").status_code == 401
        assert (
            client.patch("/v1/me/profile", headers=headers, json={"role": "administrator"}).status_code == 400
        )
        result = client.patch(
            "/v1/me/profile",
            headers=headers,
            json={"displayName": "Synthetic profile", "preferredLanguage": "en"},
        )
        assert result.status_code == 200
        service.get = AsyncMock(
            side_effect=MemberSessionFailure(status=403, code="ACCOUNT_SUSPENDED", title="Suspended")
        )
        assert client.get("/v1/me/profile", headers=headers).status_code == 403
        service.update = AsyncMock(
            side_effect=MemberSessionFailure(status=400, code="VALIDATION_FAILED", title="Invalid")
        )
        assert client.patch("/v1/me/profile", headers=headers, json={"ageGroup": None}).status_code == 400
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/me/profile", headers=headers).status_code == 503
        assert client.patch("/v1/me/profile", headers=headers, json={"ageGroup": None}).status_code == 503


def test_profile_lifespan_wires_and_releases_handler(settings):
    config = Settings.model_validate({**connected_settings(settings).model_dump(), "profile_enabled": True})
    profile = Mock()

    @asynccontextmanager
    async def factory(_):
        yield Mock(session_controls=Mock(), profile_service=profile)

    app = create_app(config, member_runtime_factory=factory)
    with TestClient(app):
        assert app.state.profile_service is profile
    assert isinstance(app.state.profile_service, UnconfiguredProfileService)
