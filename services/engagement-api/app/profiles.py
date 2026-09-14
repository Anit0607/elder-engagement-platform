"""Strict profile models for the approved Week 2 fields.

Age bands/minimum-age enforcement remain a separate client policy decision.
Time-zone existence is checked by the database-backed service, not this model.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BroadLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
    country_code: str = Field(default="IN", alias="countryCode", pattern=r"^[A-Z]{2}$")
    state: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def reject_explicit_null(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Omit optional location fields rather than sending null")
        return self


class NotificationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
    enabled: bool
    time_zone: str = Field(
        alias="timeZone", max_length=64, pattern=r"^(UTC|[A-Za-z_]+/[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)*)$"
    )
    start_local_time: str | None = Field(default=None, alias="startLocalTime")
    end_local_time: str | None = Field(default=None, alias="endLocalTime")

    @model_validator(mode="after")
    def check_window(self):
        times = (self.start_local_time, self.end_local_time)
        if self.enabled:
            if any(
                not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)
                for value in times
            ):
                raise ValueError("Enabled notification windows require two valid local times")
        elif any(value is not None for value in times):
            raise ValueError("Disabled notification windows must not contain times")
        return self


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
    display_name: str | None = Field(default=None, alias="displayName", min_length=1, max_length=120)
    preferred_language: Literal["bn", "hi", "en"] | None = Field(default=None, alias="preferredLanguage")
    age_group: str | None = Field(default=None, alias="ageGroup", max_length=64)
    interests: list[str] | None = Field(default=None, max_length=30)
    broad_location: BroadLocation | None = Field(default=None, alias="broadLocation")
    notification_window: NotificationWindow | None = Field(default=None, alias="notificationWindow")

    @model_validator(mode="after")
    def validate_partial_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        for name in self.model_fields_set - {"age_group", "broad_location"}:
            if getattr(self, name) is None:
                raise ValueError("Null is not allowed for this profile field")
        if self.display_name is not None and not self.display_name.strip():
            raise ValueError("A display name cannot be blank")
        if self.interests is not None and (
            len(set(self.interests)) != len(self.interests)
            or any(not 1 <= len(value) <= 80 or not value.strip() for value in self.interests)
        ):
            raise ValueError("Interests must be distinct nonblank strings of at most 80 characters")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: UUID
    role: Literal["member", "contributor", "administrator"]
    status: Literal["invited", "active", "suspended", "deleted"]
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    preferred_language: Literal["bn", "hi", "en"] = Field(alias="preferredLanguage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    age_group: str | None = Field(default=None, alias="ageGroup", max_length=64)
    interests: list[str]
    broad_location: BroadLocation | None = Field(default=None, alias="broadLocation")
    photo_url: str | None = Field(default=None, alias="photoUrl")
    notification_window: NotificationWindow = Field(alias="notificationWindow")
