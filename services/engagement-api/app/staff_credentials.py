"""EE-010 credential primitives/policy, not a wired sign-in or enrollment adapter.

The caller must load authoritative rows and persist failed attempts and accepted
TOTP counters under database locks. A successful check alone never issues a session.
"""

from __future__ import annotations

import asyncio
import hmac
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import pyotp
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import HashingError, InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.member_auth import MemberSessionFailure
from app.staff_auth import StaffSessionRequest

_PASSWORD_WORKERS = threading.BoundedSemaphore(2)


class PasswordCapacityUnavailable(RuntimeError):
    pass


class CredentialProtectionUnavailable(RuntimeError):
    pass


class StaffPasswords:
    """Fixed Argon2id policy; stored hashes cannot request excessive work/memory."""

    def __init__(self):
        self._hasher = PasswordHasher(
            time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
        )
        self._dummy = self.hash(secrets.token_urlsafe(32))
        self._parameters = extract_parameters(self._dummy)

    @staticmethod
    def _valid(password):
        return isinstance(password, str) and 12 <= len(password) <= 256

    def hash(self, password: str) -> str:
        if not self._valid(password):
            raise ValueError("Password must contain twelve to 256 characters")
        if not _PASSWORD_WORKERS.acquire(blocking=False):
            raise PasswordCapacityUnavailable
        try:
            return self._hasher.hash(password)
        except (HashingError, MemoryError) as exc:
            raise CredentialProtectionUnavailable from exc
        finally:
            _PASSWORD_WORKERS.release()

    def verify(self, stored: str | None, password: str) -> bool:
        if not self._valid(password):
            return False
        supported = False
        if isinstance(stored, str) and len(stored) <= 200:
            try:
                supported = extract_parameters(stored) == self._parameters
            except (InvalidHashError, ValueError):
                pass
        candidate = stored if supported else self._dummy
        if not _PASSWORD_WORKERS.acquire(blocking=False):
            raise PasswordCapacityUnavailable
        try:
            # Unknown accounts and unsupported hashes still perform a bounded check.
            return self._hasher.verify(candidate, password) and supported
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError, MemoryError) as exc:
            raise CredentialProtectionUnavailable from exc
        finally:
            # Cancellation of an awaiting coroutine cannot release a running worker.
            _PASSWORD_WORKERS.release()


class StaffAuthenticator:
    """Account-bound encrypted TOTP seeds and six-digit/30-second code checks."""

    def __init__(self, encryption_key: bytes):
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise ValueError("Authenticator encryption needs a separate 32-byte key")
        self._cipher = AESGCM(encryption_key)

    @staticmethod
    def new_seed() -> str:
        return pyotp.random_base32(length=32)

    @staticmethod
    def _aad(user_id: UUID) -> bytes:
        if not isinstance(user_id, UUID):
            raise ValueError("Authenticator account identifier is invalid")
        return b"amiko-staff-totp-v1:" + user_id.bytes

    def protect(self, user_id: UUID, seed: str) -> bytes:
        if not isinstance(seed, str) or not re.fullmatch(r"[A-Z2-7]{32}", seed):
            raise ValueError("Authenticator seed is invalid")
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, seed.encode("ascii"), self._aad(user_id))

    def matched_step(
        self, user_id: UUID, encrypted: bytes, code: str, now: datetime, last_accepted_step: int | None
    ) -> int | None:
        if now.utcoffset() is None or now.timestamp() < 30:
            raise ValueError("Authenticator clock must be timezone-aware and valid")
        if last_accepted_step is not None and (type(last_accepted_step) is not int or last_accepted_step < 0):
            raise ValueError("Authenticator counter is invalid")
        if not isinstance(encrypted, bytes) or len(encrypted) != 60:
            raise CredentialProtectionUnavailable
        try:
            seed = self._cipher.decrypt(encrypted[:12], encrypted[12:], self._aad(user_id)).decode("ascii")
            if not re.fullmatch(r"[A-Z2-7]{32}", seed):
                raise ValueError()
        except (InvalidTag, UnicodeError, ValueError) as exc:
            raise CredentialProtectionUnavailable from exc
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            return None
        otp = pyotp.TOTP(seed, digits=6, interval=30)
        current = int(now.timestamp()) // 30
        matched = None
        for step in (current - 1, current, current + 1):
            equal = hmac.compare_digest(otp.generate_otp(step), code)
            if equal and matched is None:
                matched = step
        # Refuse a rare collision matching both a used and a fresh window step.
        if matched is not None and (last_accepted_step is None or matched > last_accepted_step):
            return matched
        return None


@dataclass(frozen=True)
class StaffCredentialRecord:
    user_id: UUID
    role: str
    status: str
    password_hash: str = field(repr=False)
    second_factor_enabled: bool
    encrypted_seed: bytes | None = field(default=None, repr=False)
    last_accepted_step: int | None = None
    locked_until: datetime | None = None


class StaffCredentialVerifier:
    """Verify authoritative credentials without minting tokens or writing state."""

    def __init__(self, passwords: StaffPasswords, authenticator: StaffAuthenticator):
        self._passwords, self._authenticator = passwords, authenticator

    async def verify(
        self, record: StaffCredentialRecord | None, request: StaffSessionRequest, now: datetime
    ) -> int | None:
        if now.utcoffset() is None:
            raise ValueError("Staff sign-in clock must be timezone-aware")
        if record and record.locked_until and record.locked_until > now:
            raise MemberSessionFailure(status=429, code="RATE_LIMITED", title="Wait before signing in again")
        try:
            password_ok = await asyncio.to_thread(
                self._passwords.verify,
                record.password_hash if record else None,
                request.password.get_secret_value(),
            )
            if not password_ok or not record or record.role not in {"contributor", "administrator"}:
                raise MemberSessionFailure(
                    status=401, code="AUTHENTICATION_FAILED", title="Authentication failed"
                )
            if record.status == "suspended":
                raise MemberSessionFailure(status=403, code="ACCOUNT_SUSPENDED", title="Account is suspended")
            if record.status != "active":
                raise MemberSessionFailure(
                    status=401, code="AUTHENTICATION_FAILED", title="Authentication failed"
                )
            if record.role == "administrator" and not record.second_factor_enabled:
                raise CredentialProtectionUnavailable
            if not record.second_factor_enabled:
                return None
            if record.encrypted_seed is None:
                raise CredentialProtectionUnavailable
            if request.second_factor_code is None:
                raise MemberSessionFailure(
                    status=403, code="MFA_REQUIRED", title="Authenticator code required"
                )
            matched = self._authenticator.matched_step(
                record.user_id,
                record.encrypted_seed,
                request.second_factor_code.get_secret_value(),
                now,
                record.last_accepted_step,
            )
            if matched is None:
                raise MemberSessionFailure(
                    status=401, code="AUTHENTICATION_FAILED", title="Authentication failed"
                )
            return matched
        except PasswordCapacityUnavailable as exc:
            raise MemberSessionFailure(
                status=429, code="RATE_LIMITED", title="Wait before signing in again"
            ) from exc
        except CredentialProtectionUnavailable as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Staff sign-in protection is unavailable",
            ) from exc
