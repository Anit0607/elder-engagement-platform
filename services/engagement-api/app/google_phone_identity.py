from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any

import cachecontrol
import requests
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.member_auth import (
    PHONE_E164_PATTERN,
    AuthenticationDependencyUnavailable,
    IdentityTokenRejected,
    VerifiedPhoneIdentity,
)

FirebaseTokenVerifier = Callable[..., Mapping[str, Any]]


class BoundedCertificateRequest(Request):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 5
        return super().__call__(*args, **kwargs)


class GooglePhoneIdentityVerifier:
    """Verify a Google-issued Firebase/Identity Platform phone identity token."""

    def __init__(
        self,
        project_id: str,
        token_audience: str,
        *,
        verify_token: FirebaseTokenVerifier = id_token.verify_firebase_token,
        request: Request | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not project_id or token_audience != project_id:
            raise ValueError("phone token audience must equal the configured Google project")
        self._project_id = project_id
        self._token_audience = token_audience
        self._verify_token = verify_token
        self._now = now
        self._session = None if request is not None else cachecontrol.CacheControl(requests.Session())
        self._request = request or BoundedCertificateRequest(session=self._session)
        # The cached HTTP session is intentionally shared and serialized. This
        # avoids fetching Google's public signing certificates for every login
        # without assuming that the session is safe for simultaneous threads.
        self._verification_lock = asyncio.Lock()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    async def verify(self, provider_id_token: str) -> VerifiedPhoneIdentity:
        try:
            async with self._verification_lock:
                claims = await asyncio.to_thread(
                    self._verify_token,
                    provider_id_token,
                    self._request,
                    audience=self._token_audience,
                    clock_skew_in_seconds=30,
                )
        except (google_auth_exceptions.TransportError, requests.RequestException) as exc:
            raise AuthenticationDependencyUnavailable from exc
        except (google_auth_exceptions.GoogleAuthError, TypeError, ValueError) as exc:
            raise IdentityTokenRejected from exc

        if not isinstance(claims, Mapping) or not self._valid_claims(claims):
            raise IdentityTokenRejected

        return VerifiedPhoneIdentity(
            phone_e164=str(claims["phone_number"]),
            provider_subject=str(claims["sub"]),
        )

    def _valid_claims(self, claims: Mapping[str, Any]) -> bool:
        subject = claims.get("sub")
        phone = claims.get("phone_number")
        firebase = claims.get("firebase")
        auth_time = claims.get("auth_time")
        return bool(
            claims.get("iss") == f"https://securetoken.google.com/{self._project_id}"
            and claims.get("aud") == self._token_audience
            and isinstance(subject, str)
            and 1 <= len(subject) <= 128
            and isinstance(phone, str)
            and PHONE_E164_PATTERN.fullmatch(phone)
            and isinstance(firebase, Mapping)
            and firebase.get("sign_in_provider") == "phone"
            and isinstance(auth_time, int)
            and not isinstance(auth_time, bool)
            and 0 < auth_time <= self._now() + 30
        )
