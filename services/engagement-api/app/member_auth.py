from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PHONE_E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")


class MemberSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider_id_token: str = Field(alias="providerIdToken", min_length=20, max_length=8192)
    installation_id: UUID = Field(alias="installationId")
    platform: Literal["android", "ios"]
    device_name: str | None = Field(default=None, alias="deviceName", max_length=120)


class UserSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    role: Literal["member"]
    status: Literal["active"]
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    preferred_language: Literal["bn", "hi"] = Field(alias="preferredLanguage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    access_token: str = Field(alias="accessToken", min_length=1)
    refresh_token: str = Field(alias="refreshToken", min_length=1)
    token_type: Literal["Bearer"] = Field(alias="tokenType", default="Bearer")
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=60, le=3600)
    user: UserSummary


@dataclass(frozen=True)
class VerifiedPhoneIdentity:
    phone_e164: str
    provider_subject: str


@dataclass(frozen=True)
class MemberRecord:
    id: UUID
    role: str
    status: str
    display_name: str
    preferred_language: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in_seconds: int


class PhoneIdentityVerifier(Protocol):
    async def verify(self, provider_id_token: str) -> VerifiedPhoneIdentity: ...


class MemberRepository(Protocol):
    async def claim_verified_member(
        self, phone_e164: str, provider_subject: str
    ) -> MemberRecord | None: ...


class SessionIssuer(Protocol):
    async def issue(
        self,
        member: MemberRecord,
        installation_id: UUID,
        platform: Literal["android", "ios"],
        device_name: str | None,
    ) -> IssuedSession: ...


class IdentityTokenRejected(RuntimeError):
    """The external identity token is invalid or lacks a verified phone."""


class AuthenticationDependencyUnavailable(RuntimeError):
    """A required identity or session dependency is temporarily unavailable."""


class MemberSessionFailure(RuntimeError):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.code = code
        self.title = title
        self.retryable = retryable


class MemberSessionService:
    def __init__(
        self,
        verifier: PhoneIdentityVerifier,
        repository: MemberRepository,
        session_issuer: SessionIssuer,
    ) -> None:
        self._verifier = verifier
        self._repository = repository
        self._session_issuer = session_issuer

    async def create(self, request: MemberSessionRequest) -> SessionResponse:
        try:
            identity = await self._verifier.verify(request.provider_id_token)
        except IdentityTokenRejected as exc:
            raise MemberSessionFailure(
                status=401,
                code="AUTHENTICATION_FAILED",
                title="Authentication failed",
            ) from exc
        except AuthenticationDependencyUnavailable as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Authentication service is temporarily unavailable",
                retryable=True,
            ) from exc

        if not PHONE_E164_PATTERN.fullmatch(identity.phone_e164) or not identity.provider_subject:
            raise MemberSessionFailure(
                status=401,
                code="AUTHENTICATION_FAILED",
                title="Authentication failed",
            )

        try:
            member = await self._repository.claim_verified_member(
                identity.phone_e164, identity.provider_subject
            )
        except AuthenticationDependencyUnavailable as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Authentication service is temporarily unavailable",
                retryable=True,
            ) from exc

        if member is None:
            raise MemberSessionFailure(
                status=403,
                code="PROFILE_NOT_PROVISIONED",
                title="Member profile is not provisioned",
            )
        if member.role != "member" or member.status == "deleted":
            raise MemberSessionFailure(
                status=401,
                code="AUTHENTICATION_FAILED",
                title="Authentication failed",
            )
        if member.status == "suspended":
            raise MemberSessionFailure(
                status=403,
                code="ACCOUNT_SUSPENDED",
                title="Account is suspended",
            )
        if member.status != "active":
            raise MemberSessionFailure(
                status=401,
                code="AUTHENTICATION_FAILED",
                title="Authentication failed",
            )

        try:
            issued = await self._session_issuer.issue(
                member,
                request.installation_id,
                request.platform,
                request.device_name,
            )
        except AuthenticationDependencyUnavailable as exc:
            raise MemberSessionFailure(
                status=503,
                code="DEPENDENCY_UNAVAILABLE",
                title="Authentication service is temporarily unavailable",
                retryable=True,
            ) from exc

        return SessionResponse(
            accessToken=issued.access_token,
            refreshToken=issued.refresh_token,
            expiresInSeconds=issued.expires_in_seconds,
            user=UserSummary(
                id=member.id,
                role="member",
                status="active",
                displayName=member.display_name,
                preferredLanguage=member.preferred_language,
                createdAt=member.created_at,
                updatedAt=member.updated_at,
            ),
        )


class UnconfiguredMemberSessionService:
    async def create(self, request: MemberSessionRequest) -> SessionResponse:
        del request
        raise MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Authentication service is temporarily unavailable",
            retryable=True,
        )


class MemberSessionHandler(Protocol):
    async def create(self, request: MemberSessionRequest) -> SessionResponse: ...
