import asyncio
import base64
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from argon2 import extract_parameters

from app import staff_credentials as credentials
from app.logging_config import redact, sanitize
from app.member_auth import MemberSessionFailure
from app.staff_auth import StaffSessionRequest
from app.staff_credentials import (
    CredentialProtectionUnavailable,
    PasswordCapacityUnavailable,
    StaffAuthenticator,
    StaffCredentialRecord,
    StaffCredentialVerifier,
    StaffPasswords,
)

PASSWORD = "synthetic-not-a-working-password"  # noqa: S105 - non-working fixture
WRONG_PASSWORD = "synthetic-wrong-password"  # noqa: S105 - non-working fixture
USER = UUID("11111111-1111-4111-8111-111111111111")
KEY = bytes(range(32))  # Synthetic encryption key, never used by a live account.
RFC_SEED = base64.b32encode(b"12345678901234567890").decode("ascii")
NOW = datetime.fromtimestamp(59, UTC)


@pytest.fixture(scope="module")
def passwords():
    return StaffPasswords()


@pytest.fixture(scope="module")
def stored(passwords):
    return passwords.hash(PASSWORD)


def request(**changes):
    return StaffSessionRequest.model_validate(
        {
            "username": "synthetic.staff",
            "password": PASSWORD,
            "installationId": str(uuid4()),
            "platform": "web",
            **changes,
        }
    )


def record(stored, **changes):
    return replace(StaffCredentialRecord(USER, "contributor", "active", stored, False), **changes)


def authenticator():
    return StaffAuthenticator(KEY)


def test_password_hashes_are_salted_and_follow_fixed_argon2id_policy(passwords, stored):
    second = passwords.hash(PASSWORD)
    assert second != stored
    assert PASSWORD not in stored
    parameters = extract_parameters(stored)
    assert parameters.memory_cost == 19_456
    assert parameters.time_cost == 2
    assert parameters.parallelism == 1
    assert parameters.salt_len == 16
    assert parameters.hash_len == 32
    assert passwords.verify(stored, PASSWORD)
    assert not passwords.verify(stored, "synthetic-wrong-password")


@pytest.mark.parametrize("bad", [None, "short", 123456789012, "x" * 257])
def test_invalid_password_input_is_not_hashed_or_accepted(passwords, stored, bad):
    with pytest.raises(ValueError):
        passwords.hash(bad)
    assert not passwords.verify(stored, bad)


def test_unicode_password_is_supported_without_silent_truncation(passwords):
    password = "বাংলা हिन्दी English " * 3
    encoded = passwords.hash(password)
    assert passwords.verify(encoded, password)
    assert not passwords.verify(encoded, password + "x")


@pytest.mark.parametrize(
    "bad", [None, "plaintext-not-a-hash", "$argon2id$v=19$m=999999999,t=2,p=1$x$x", "x" * 201]
)
def test_unknown_or_unsupported_hash_uses_only_bounded_dummy_work(passwords, monkeypatch, bad):
    candidates = []
    monkeypatch.setattr(
        type(passwords._hasher), "verify", lambda self, encoded, value: candidates.append(encoded) or True
    )
    assert not passwords.verify(bad, PASSWORD)
    assert candidates == [passwords._dummy]


def test_password_worker_slots_stay_bounded(passwords, stored):
    semaphore = credentials._PASSWORD_WORKERS
    assert semaphore.acquire(blocking=False)
    assert semaphore.acquire(blocking=False)
    try:
        with pytest.raises(PasswordCapacityUnavailable):
            passwords.hash(PASSWORD)
        with pytest.raises(PasswordCapacityUnavailable):
            passwords.verify(stored, PASSWORD)
    finally:
        semaphore.release()
        semaphore.release()
    assert passwords.verify(stored, PASSWORD)


def test_hashing_failure_fails_closed_and_releases_worker(passwords, monkeypatch):
    def unavailable(self, value):
        raise MemoryError()

    with monkeypatch.context() as patch:
        patch.setattr(type(passwords._hasher), "hash", unavailable)
        with pytest.raises(CredentialProtectionUnavailable):
            passwords.hash(PASSWORD)
    assert passwords.verify(passwords.hash(PASSWORD), PASSWORD)


def test_authenticator_seed_generation_and_encryption_are_random_and_account_bound():
    checker = authenticator()
    seed = checker.new_seed()
    assert len(seed) == 32
    assert seed != checker.new_seed()
    first, second = checker.protect(USER, RFC_SEED), checker.protect(USER, RFC_SEED)
    assert len(first) == 60
    assert first != second
    assert RFC_SEED.encode() not in first
    with pytest.raises(CredentialProtectionUnavailable):
        checker.matched_step(uuid4(), first, "287082", NOW, None)


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_matches_rfc6238_sha1_vectors_as_six_digit_codes(timestamp, expected):
    checker = authenticator()
    encrypted = checker.protect(USER, RFC_SEED)
    step = checker.matched_step(USER, encrypted, expected[-6:], datetime.fromtimestamp(timestamp, UTC), None)
    assert step == timestamp // 30


def test_used_code_counter_is_rejected_and_small_clock_drift_is_allowed():
    checker = authenticator()
    encrypted = checker.protect(USER, RFC_SEED)
    assert checker.matched_step(USER, encrypted, "287082", NOW, None) == 1
    assert checker.matched_step(USER, encrypted, "287082", NOW, 1) is None
    assert checker.matched_step(USER, encrypted, "287082", NOW + timedelta(seconds=30), None) == 1
    assert checker.matched_step(USER, encrypted, "287082", NOW + timedelta(seconds=60), None) is None


@pytest.mark.parametrize("code", ["short", "94287082", "১২৩৪৫৬", " 287082", None, 287082])
def test_authenticator_rejects_wrong_format_without_coercion(code):
    checker = authenticator()
    assert checker.matched_step(USER, checker.protect(USER, RFC_SEED), code, NOW, None) is None


@pytest.mark.parametrize("bad", [b"short", "not-bytes", b"x" * 60])
def test_corrupt_authenticator_data_fails_closed(bad):
    with pytest.raises(CredentialProtectionUnavailable):
        authenticator().matched_step(USER, bad, "287082", NOW, None)


def test_wrong_encryption_key_and_tampered_ciphertext_fail_closed():
    encrypted = authenticator().protect(USER, RFC_SEED)
    wrong_key = StaffAuthenticator(b"x" * 32)
    with pytest.raises(CredentialProtectionUnavailable):
        wrong_key.matched_step(USER, encrypted, "287082", NOW, None)
    tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    with pytest.raises(CredentialProtectionUnavailable):
        authenticator().matched_step(USER, tampered, "287082", NOW, None)


@pytest.mark.parametrize("bad", [b"short", "x" * 32, b"x" * 31, b"x" * 33])
def test_encryption_key_length_and_type_are_strict(bad):
    with pytest.raises(ValueError):
        StaffAuthenticator(bad)


@pytest.mark.parametrize("bad", ["short", "x" * 32, b"x" * 32])
def test_invalid_seed_is_not_protected(bad):
    with pytest.raises(ValueError):
        authenticator().protect(USER, bad)


@pytest.mark.parametrize(
    "clock,counter",
    [(datetime(2026, 9, 14), None), (NOW, -1), (NOW, True), (datetime.fromtimestamp(0, UTC), None)],
)
def test_clock_and_counter_inputs_fail_closed(clock, counter):
    checker = authenticator()
    with pytest.raises(ValueError):
        checker.matched_step(USER, checker.protect(USER, RFC_SEED), "287082", clock, counter)


@pytest.mark.anyio
async def test_contributor_checks_real_password_without_requiring_mfa(passwords, stored):
    verifier = StaffCredentialVerifier(passwords, authenticator())
    assert await verifier.verify(record(stored), request(), NOW) is None


@pytest.mark.anyio
async def test_administrator_requires_verified_code_and_rejects_reuse(passwords, stored):
    checker = authenticator()
    account = record(
        stored,
        role="administrator",
        second_factor_enabled=True,
        encrypted_seed=checker.protect(USER, RFC_SEED),
    )
    verifier = StaffCredentialVerifier(passwords, checker)
    with pytest.raises(MemberSessionFailure) as missing:
        await verifier.verify(account, request(), NOW)
    assert missing.value.code == "MFA_REQUIRED"
    assert await verifier.verify(account, request(secondFactorCode="287082"), NOW) == 1
    with pytest.raises(MemberSessionFailure) as reused:
        await verifier.verify(replace(account, last_accepted_step=1), request(secondFactorCode="287082"), NOW)
    assert reused.value.code == "AUTHENTICATION_FAILED"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes,status",
    [
        ({"role": "member"}, 401),
        ({"status": "invited"}, 401),
        ({"status": "deleted"}, 401),
        ({"status": "suspended"}, 403),
        ({"locked_until": NOW + timedelta(minutes=10)}, 429),
        ({"role": "administrator", "second_factor_enabled": False}, 503),
        ({"role": "administrator", "second_factor_enabled": True}, 503),
    ],
)
async def test_account_policy_never_accepts_invalid_or_incomplete_staff(passwords, stored, changes, status):
    verifier = StaffCredentialVerifier(passwords, authenticator())
    with pytest.raises(MemberSessionFailure) as error:
        await verifier.verify(record(stored, **changes), request(), NOW)
    assert error.value.status == status


@pytest.mark.anyio
async def test_unknown_account_and_wrong_password_are_generic_failures(passwords, stored):
    verifier = StaffCredentialVerifier(passwords, authenticator())
    for account in [None, record(stored, status="suspended")]:
        with pytest.raises(MemberSessionFailure) as error:
            await verifier.verify(account, request(password=WRONG_PASSWORD), NOW)
        assert error.value.code == "AUTHENTICATION_FAILED"


def test_credential_record_repr_omits_protected_values(stored):
    encrypted = authenticator().protect(USER, RFC_SEED)
    value = repr(record(stored, encrypted_seed=encrypted))
    assert stored not in value
    assert repr(encrypted) not in value


@pytest.mark.anyio
async def test_enabled_contributor_second_factor_is_also_enforced(passwords, stored):
    checker = authenticator()
    account = record(stored, second_factor_enabled=True, encrypted_seed=checker.protect(USER, RFC_SEED))
    verifier = StaffCredentialVerifier(passwords, checker)
    assert await verifier.verify(account, request(secondFactorCode="287082"), NOW) == 1
    with pytest.raises(MemberSessionFailure) as error:
        await verifier.verify(account, request(secondFactorCode="94287082"), NOW)
    assert error.value.code == "AUTHENTICATION_FAILED"


@pytest.mark.anyio
async def test_bad_encrypted_setup_becomes_safe_dependency_failure(passwords, stored):
    account = record(stored, role="administrator", second_factor_enabled=True, encrypted_seed=b"bad")
    with pytest.raises(MemberSessionFailure) as error:
        await StaffCredentialVerifier(passwords, authenticator()).verify(
            account,
            request(secondFactorCode="287082"),
            NOW,
        )
    assert error.value.status == 503
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.anyio
async def test_password_worker_capacity_becomes_safe_rate_limit(passwords, stored, monkeypatch):
    def unavailable(stored, password):
        raise PasswordCapacityUnavailable()

    monkeypatch.setattr(passwords, "verify", unavailable)
    with pytest.raises(MemberSessionFailure) as error:
        await StaffCredentialVerifier(passwords, authenticator()).verify(record(stored), request(), NOW)
    assert error.value.code == "RATE_LIMITED"


@pytest.mark.anyio
async def test_password_dependency_failure_does_not_grant_access(passwords, stored, monkeypatch):
    def unavailable(stored, password):
        raise CredentialProtectionUnavailable()

    monkeypatch.setattr(passwords, "verify", unavailable)
    with pytest.raises(MemberSessionFailure) as error:
        await StaffCredentialVerifier(passwords, authenticator()).verify(record(stored), request(), NOW)
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.anyio
async def test_staff_policy_rejects_naive_clock(passwords, stored):
    with pytest.raises(ValueError):
        await StaffCredentialVerifier(passwords, authenticator()).verify(
            record(stored),
            request(),
            datetime(2026, 9, 14),
        )


def test_verification_engine_failure_fails_closed_and_releases_worker(passwords, stored, monkeypatch):
    def unavailable(self, encoded, value):
        raise MemoryError()

    with monkeypatch.context() as patch:
        patch.setattr(type(passwords._hasher), "verify", unavailable)
        with pytest.raises(CredentialProtectionUnavailable):
            passwords.verify(stored, PASSWORD)
    assert passwords.verify(stored, PASSWORD)


def test_invalid_account_identifier_cannot_protect_seed():
    with pytest.raises(ValueError):
        authenticator().protect(str(USER), RFC_SEED)


def test_authenticated_but_invalid_seed_format_fails_closed():
    checker = authenticator()
    nonce = bytes(range(12))  # Inert vector only; actual protect generates random nonces.
    encrypted = nonce + checker._cipher.encrypt(nonce, b"x" * 32, checker._aad(USER))
    with pytest.raises(CredentialProtectionUnavailable):
        checker.matched_step(USER, encrypted, "287082", NOW, None)


@pytest.mark.anyio
async def test_cancelled_request_does_not_release_a_still_running_password_worker(
    passwords, stored, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def held_verify(self, encoded, value):
        started.set()
        assert release.wait(timeout=2)
        return True

    def check():
        try:
            return passwords.verify(stored, PASSWORD)
        finally:
            finished.set()

    monkeypatch.setattr(type(passwords._hasher), "verify", held_verify)
    task = asyncio.create_task(asyncio.to_thread(check))
    held_other_slot = False
    try:
        assert await asyncio.to_thread(started.wait, 2)
        held_other_slot = credentials._PASSWORD_WORKERS.acquire(blocking=False)
        assert held_other_slot
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(PasswordCapacityUnavailable):
            passwords.verify(stored, PASSWORD)
    finally:
        release.set()
        if held_other_slot:
            credentials._PASSWORD_WORKERS.release()
        assert await asyncio.to_thread(finished.wait, 2)


def test_ambiguous_code_collision_never_allows_a_used_step_replay(monkeypatch):
    monkeypatch.setattr(
        credentials.pyotp, "TOTP", lambda *args, **kwargs: SimpleNamespace(generate_otp=lambda step: "287082")
    )
    checker = authenticator()
    encrypted = checker.protect(USER, RFC_SEED)
    assert checker.matched_step(USER, encrypted, "287082", NOW, None) == 0
    assert checker.matched_step(USER, encrypted, "287082", NOW, 0) is None


@pytest.mark.parametrize(
    "key",
    [
        "password_hash",
        "secondFactorCode",
        "second_factor_code",
        "encrypted_seed",
        "mfa_secret_ciphertext",
        "totpSeed",
        "provisioningUri",
    ],
)
def test_staff_setup_fields_are_redacted_in_nested_log_context(key):
    assert sanitize({"nested": {key: "synthetic-private-marker"}})["nested"][key] == "[REDACTED]"


def test_staff_fields_are_redacted_in_text_logs():
    message = 'password_hash="synthetic-hash-marker" secondFactorCode=654321 encrypted_seed="cipher-marker"'
    safe = redact(message)
    assert "synthetic-hash-marker" not in safe
    assert "654321" not in safe
    assert "cipher-marker" not in safe


def test_authenticator_setup_url_is_redacted_even_without_a_named_field():
    uri = "otpauth://totp/synthetic-account?secret=synthetic-seed-marker&issuer=Amiko"
    assert redact("setup " + uri) == "setup [REDACTED]"
