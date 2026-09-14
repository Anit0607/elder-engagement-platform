"""Validated EE-010 interface; real credential activation is not wired yet."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.member_auth import MemberSessionFailure


class StaffSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    username: str = Field(min_length=3, max_length=120, strict=True)
    password: SecretStr = Field(min_length=12, max_length=256)
    second_factor_code: SecretStr | None = Field(
        default=None, alias="secondFactorCode", json_schema_extra={"pattern": "^[0-9]{6,8}$"},
    )
    installation_id: UUID = Field(alias="installationId")
    platform: Literal["android", "ios", "web"]
    device_name: str | None = Field(default=None, alias="deviceName", max_length=120)

    @field_validator("second_factor_code", mode="before")
    @classmethod
    def code_shape(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9]{6,8}", value)):
            raise ValueError("Second factor must contain six to eight ASCII digits")
        return value


class StaffUserSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    role: Literal["contributor", "administrator"]
    status: Literal["active"]
    display_name: str | None = Field(default=None, alias="displayName", min_length=1, max_length=120)
    preferred_language: Literal["bn", "hi"] | None = Field(default=None, alias="preferredLanguage")
    profile_complete: bool = Field(alias="profileComplete")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class StaffSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    access_token: str = Field(alias="accessToken", min_length=1, repr=False)
    refresh_token: str = Field(alias="refreshToken", min_length=1, repr=False)
    token_type: Literal["Bearer"] = Field(alias="tokenType", default="Bearer")
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=60, le=3600)
    user: StaffUserSummary


class StaffSessionHandler(Protocol):
    """Adapter must authenticate stored credentials/role and Administrator MFA.

    The production adapter must enforce activation, suspension, throttling,
    one-time second-factor use and account/session locks before issuing tokens.
    No client-supplied role or test-success implementation is accepted by runtime.
    """

    async def create(self, request: StaffSessionRequest) -> StaffSessionResponse: ...


class UnconfiguredStaffSessionService:
    async def create(self, request: StaffSessionRequest) -> StaffSessionResponse:
        del request
        raise MemberSessionFailure(
            status=503,
            code="DEPENDENCY_UNAVAILABLE",
            title="Staff sign-in is not configured",
            retryable=False,
        )
