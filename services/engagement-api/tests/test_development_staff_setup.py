import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app import development_staff_setup as setup
from app.config import ConfigurationError
from app.logging_config import sanitize
from app.member_auth import MemberSessionFailure


def inputs():
    return setup.FictionalSetupInput(
        administrator_password="synthetic-admin-password-only",  # noqa: S106 -- non-working unit fixture
        contributor_password="synthetic-contributor-password-only",  # noqa: S106 -- non-working unit fixture
        administrator_seed="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
    )


def environment():
    return dict(
        STAFF_SETUP_MODE="fictional-development",
        STAFF_SETUP_PROJECT="example-development-project",
        CLOUD_RUN_JOB="ee-development-fictional-staff-setup",
        CLOUD_RUN_EXECUTION="fictional-execution",
        SOURCE_REVISION="a" * 40,
    )


def settings(**changes):
    return SimpleNamespace(
        environment="development",
        staff_session_enabled=True,
        gcp_project_id="example-development-project",
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"STAFF_SETUP_MODE": "production"},
        {"STAFF_SETUP_PROJECT": "other"},
        {"CLOUD_RUN_JOB": "other"},
        {"CLOUD_RUN_EXECUTION": ""},
        {"SOURCE_REVISION": "invalid"},
    ],
)
def test_job_environment_guard(changes):
    env = environment()
    env.update(changes)
    with pytest.raises(ConfigurationError):
        setup.guard_job(settings(), env)


def test_job_guard_requires_development_and_staff_runtime():
    for name, value in [("environment", "production"), ("staff_session_enabled", False)]:
        config = settings()
        setattr(config, name, value)
        with pytest.raises(ConfigurationError):
            setup.guard_job(config, environment())
    setup.guard_job(settings(), environment())


def test_input_rejects_short_passwords_extra_fields_and_repr_exposure():
    fixture = inputs()
    assert fixture.administrator_seed.get_secret_value() not in repr(fixture)
    assert fixture.administrator_password.get_secret_value() not in repr(fixture)
    for change in [{"administrator_password": "short"}, {"username": "not-accepted"}]:
        with pytest.raises(ValidationError):
            setup.FictionalSetupInput(**{**fixture.model_dump(), **change})


@pytest.mark.parametrize(
    "name",
    [
        "administrator_password",
        "contributor_password",
        "administrator_seed",
        "AMIKO_FICTIONAL_STAFF_SETUP_INPUT",
    ],
)
def test_private_setup_input_names_redacted(name):
    assert sanitize({name: "synthetic-private-value"}) == {name: "[REDACTED]"}


@pytest.mark.anyio
async def test_bound_pool_does_not_acquire_another_connection():
    connection = object()
    async with setup.BoundPool(connection).acquire() as selected:
        assert selected is connection


def test_member_proof_is_always_rejected():
    with pytest.raises(MemberSessionFailure):
        setup.RejectMemberProof()._claims("not-a-staff-proof")


@pytest.mark.anyio
@pytest.mark.parametrize("raw", ["", "x" * 4097])
async def test_run_refuses_missing_or_oversized_private_input(monkeypatch, raw):
    monkeypatch.setattr(setup, "load_settings", lambda env: settings())
    with pytest.raises(ConfigurationError):
        await setup.run({**environment(), "AMIKO_FICTIONAL_STAFF_SETUP_INPUT": raw})


@pytest.mark.anyio
async def test_run_uses_existing_private_runtime_and_returns_no_secrets(monkeypatch):
    config = settings()
    config.public_api_origin, config.access_token_minutes, config.refresh_token_days = (
        "https://synthetic.run.app",
        10,
        30,
    )
    monkeypatch.setattr(setup, "load_settings", lambda env: config)
    monkeypatch.setattr(setup, "_session_secret", lambda env, name: bytes(range(32)))
    monkeypatch.setattr(setup, "StaffPasswords", Mock)
    pool = object()

    @asynccontextmanager
    async def runtime(*args, **kwargs):
        yield SimpleNamespace(staff_session_handler=SimpleNamespace(_pool=pool))

    monkeypatch.setattr(setup, "member_runtime", runtime)
    fixture = AsyncMock(return_value=["fictional-check"])
    monkeypatch.setattr(setup, "create_fictional_fixture", fixture)
    result = await setup.run(
        {
            **environment(),
            "AMIKO_FICTIONAL_STAFF_SETUP_INPUT": json.dumps(
                {name: value.get_secret_value() for name, value in inputs().model_dump().items()}
            ),
        }
    )
    assert result["status"] == "ok" and result["fictional_only"] is True
    assert result["client_authenticator_acceptance"] is False and result["public_route_enabled"] is False
    assert fixture.await_args.args[0] is pool
    assert inputs().administrator_password.get_secret_value() not in str(result)


def test_main_never_prints_private_exception_details(monkeypatch, capsys):
    async def failure():
        raise RuntimeError("synthetic-secret-that-must-not-be-printed")

    monkeypatch.setattr(setup, "run", failure)
    assert setup.main() == 1
    output = capsys.readouterr().out
    assert '"status": "failed"' in output and "synthetic-secret-that-must-not-be-printed" not in output


def test_main_reports_success_without_private_inputs(monkeypatch, capsys):
    async def success():
        return {"status": "ok", "fictional_only": True}

    monkeypatch.setattr(setup, "run", success)
    assert setup.main() == 0
    assert '"status": "ok"' in capsys.readouterr().out


class FixtureDatabase:
    def __init__(self):
        self.committed = False

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield self
        self.committed = True


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [None, "admin", "contributor", "wrong-denial", "no-denial"])
async def test_fixture_orchestration_commits_only_when_all_checks_pass(monkeypatch, failure):
    db = FixtureDatabase()
    enrollment = Mock()
    enrollment.bootstrap_development_administrator = AsyncMock(
        return_value=SimpleNamespace(id="fictional-admin")
    )
    rejected = MemberSessionFailure(
        status=401 if failure == "wrong-denial" else 403, code="FORBIDDEN", title="Synthetic denial"
    )
    enrollment.create_contributor = AsyncMock(
        side_effect=[
            SimpleNamespace(id="fictional-contributor"),
            None if failure == "no-denial" else rejected,
        ]
    )
    staff = Mock()
    staff.create = AsyncMock(
        side_effect=[
            SimpleNamespace(
                user=SimpleNamespace(
                    id="bad" if failure == "admin" else "fictional-admin", role="administrator"
                ),
                access_token="fictional-admin-proof",  # noqa: S106 -- non-working unit fixture
            ),
            SimpleNamespace(
                user=SimpleNamespace(
                    id="bad" if failure == "contributor" else "fictional-contributor", role="contributor"
                ),
                access_token="fictional-contributor-proof",  # noqa: S106 -- non-working unit fixture
            ),
        ]
    )
    controls = Mock(logout=AsyncMock())
    monkeypatch.setattr(setup, "PostgresStaffEnrollment", lambda *args, **kwargs: enrollment)
    monkeypatch.setattr(setup, "PostgresStaffSessionService", lambda *args, **kwargs: staff)
    monkeypatch.setattr(setup, "PostgresStaffSessionControls", lambda *args, **kwargs: controls)
    monkeypatch.setattr(setup, "SessionAuthorization", Mock)
    if failure:
        with pytest.raises(ConfigurationError):
            await setup.create_fictional_fixture(db, inputs(), Mock(), Mock(), {})
        assert not db.committed
    else:
        checks = await setup.create_fictional_fixture(db, inputs(), Mock(), Mock(), {})
        assert len(checks) == 4 and db.committed and controls.logout.await_count == 2


@pytest.mark.anyio
async def test_fixture_rejects_invalid_seed_before_database_access():
    db = FixtureDatabase()
    fixture = inputs()
    fixture.administrator_seed = setup.SecretStr("x" * 32)
    with pytest.raises(ConfigurationError):
        await setup.create_fictional_fixture(db, fixture, Mock(), Mock(), {})
    assert not db.committed
