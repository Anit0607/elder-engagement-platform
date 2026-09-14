import io
import json
from unittest.mock import Mock

import pytest

from tools import development_staff_test_page as page
from tools.test_development_member_login import SafeTestFailure


def trial():
    return page.StaffTrial(
        "https://synthetic.run.app",
        page.FictionalSetupInput(
            administrator_password="synthetic-admin-password-only",  # noqa: S106 -- not a runtime credential
            contributor_password="synthetic-contributor-password-only",  # noqa: S106 -- not a runtime credential
            administrator_seed="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        ),
    )


def session(role="administrator", *, identity="fictional-user"):
    return dict(
        accessToken="fictional-access",
        refreshToken="fictional-refresh",
        user=dict(id=identity, role=role, preferredLanguage="en"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"action": "unknown"},
        {"action": "login", "role": "member"},
        {"action": "login", "role": "administrator", "code": 123456},
        {"action": "login", "role": "administrator", "code": "１２３４５６"},
        {"action": "login", "role": "administrator", "username": "other-account"},
    ],
)
def test_invalid_requests_never_reach_cloud(payload):
    handler = trial()
    handler.call = Mock(side_effect=AssertionError("Must not reach cloud"))
    assert handler.perform(payload)[0] == 400


@pytest.mark.parametrize("role", ["administrator", "contributor"])
def test_only_fixed_fictional_accounts_used_and_no_credentials_returned(role):
    handler = trial()
    handler.call = Mock(return_value=(200, session(role)))
    status, result = handler.perform({"action": "login", "role": role, "code": "000001"})
    assert status == 200 and result["role"] == role
    body = handler.call.call_args.args[2]
    assert body["username"] == "fictional.ee010." + role
    assert ("secondFactorCode" in body) == (role == "administrator")
    assert "Token" not in json.dumps(result) and "password" not in json.dumps(result)
    assert handler.inputs.administrator_seed.get_secret_value() not in json.dumps(result)


def test_missing_code_is_sent_without_bypassing_mfa():
    handler = trial()
    handler.call = Mock(return_value=(403, {}))
    assert handler.perform({"action": "login", "role": "administrator"})[0] == 403
    assert "secondFactorCode" not in handler.call.call_args.args[2]


def test_role_mismatch_never_keeps_session():
    handler = trial()
    handler.call = Mock(return_value=(200, session("contributor")))
    assert handler.perform({"action": "login", "role": "administrator"})[0] == 503
    assert handler.session is None


@pytest.mark.parametrize("action", ["refresh", "logout", "check"])
def test_controls_require_a_session(action):
    assert trial().perform({"action": action})[0] == 400


def test_login_signs_out_old_trial_before_switching_accounts():
    handler = trial()
    handler.session = session()
    handler.call = Mock(side_effect=[(204, {}), (200, session("contributor"))])
    assert handler.perform({"action": "login", "role": "contributor"})[0] == 200
    assert handler.call.call_args_list[0].args == ("POST", "/v1/auth/logout")


def test_uncertain_old_signout_does_not_start_another_login():
    handler = trial()
    handler.session = session()
    handler.call = Mock(return_value=(503, {}))
    assert handler.perform({"action": "login", "role": "contributor"})[0] == 503
    assert handler.call.call_count == 1


@pytest.mark.parametrize(
    "outcome",
    [(503, {}), (409, {}), SafeTestFailure("private detail"), (200, session(identity="different-user"))],
)
def test_uncertain_or_invalid_renewal_is_not_replayed(outcome):
    handler = trial()
    handler.session = session()
    handler.call = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    assert handler.perform({"action": "refresh"})[0] in {503, 409}
    assert handler.session is None
    assert handler.perform({"action": "refresh"})[0] == 400
    assert handler.call.call_count == 1


def test_refresh_profile_and_signout_return_only_safe_status():
    handler = trial()
    handler.session = session()
    handler.call = Mock(side_effect=[(200, session()), (200, {"displayName": "Not returned"}), (204, {})])
    assert handler.perform({"action": "refresh"})[0] == 200
    assert "Not returned" not in str(handler.perform({"action": "check"}))
    assert handler.perform({"action": "logout"})[0] == 200 and handler.session is None


def request_handler(headers=None, *, address="127.0.0.1", path="/test"):
    handler = object.__new__(page.TrialPage)
    handler.headers = {
        "Host": "127.0.0.1:8788",
        "Origin": page.PAGE_ORIGIN,
        "X-Amiko-Trial": "fictional-csrf",
        "Content-Length": "18",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    handler.client_address, handler.path, handler.csrf = (address, 0), path, "fictional-csrf"
    handler.reply, handler.trial, handler.connection = Mock(), Mock(), Mock()
    handler.rfile = io.BytesIO(b'{"action":"check"}')
    handler.trial.perform.return_value = (200, {"message": "Test succeeded"})
    return handler


@pytest.mark.parametrize(
    "headers", [{"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"X-Amiko-Trial": "wrong"}]
)
def test_cross_site_requests_are_rejected_before_trial(headers):
    handler = request_handler(headers)
    handler.do_POST()
    assert handler.reply.call_args.args[0] == 403
    handler.trial.perform.assert_not_called()


def test_non_loopback_client_and_unknown_path_rejected():
    for handler in [request_handler(address="10.1.1.1"), request_handler(path="/other")]:
        handler.do_POST()
        assert handler.reply.call_args.args[0] == 403
        handler.trial.perform.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Length": "2049"},
        {"Content-Length": "0"},
        {"Transfer-Encoding": "chunked"},
        {"Content-Type": "text/plain"},
    ],
)
def test_bad_request_framing_never_reaches_cloud(headers):
    handler = request_handler(headers)
    handler.do_POST()
    assert handler.reply.call_args.args[0] == 400
    handler.trial.perform.assert_not_called()


def test_valid_local_request_uses_trial_and_hides_exceptions():
    handler = request_handler()
    handler.do_POST()
    assert handler.reply.call_args.args[0] == 200
    handler = request_handler()
    handler.trial.perform.side_effect = RuntimeError("private value")
    handler.do_POST()
    assert handler.reply.call_args.args[0] == 503 and b"private value" not in handler.reply.call_args.args[1]


def test_page_contains_nonce_and_no_password_input_or_remote_resources():
    handler = request_handler(path="/")
    handler.do_GET()
    html = handler.reply.call_args.args[1].decode()
    assert 'nonce="fictional-csrf"' in html and "__CSRF__" not in html
    assert "https://" not in html and 'type="password"' not in html
    assert ".join('\\n')" in html
