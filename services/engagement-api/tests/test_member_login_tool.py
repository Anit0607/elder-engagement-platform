from __future__ import annotations

import pytest

from tools.test_development_member_login import SafeTestFailure, select_fictional_identity


def test_live_test_uses_only_registered_fictional_identity():
    config = {"signIn": {"phoneNumber": {"testPhoneNumbers": {"+911234567890": "123456"}}}}
    assert select_fictional_identity(config) == ("+911234567890", "123456")


@pytest.mark.parametrize("pairs", [{}, {"+16505550100": "123456"}, {"+911234567890": "bad"}])
def test_live_test_refuses_missing_or_wrong_region_fictional_identity(pairs):
    with pytest.raises(SafeTestFailure):
        select_fictional_identity({"signIn": {"phoneNumber": {"testPhoneNumbers": pairs}}})
