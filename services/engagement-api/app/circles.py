"""Predefined circle requests, responses and suggestion rules."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CircleSuggestionRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    interests: list[str] = Field(default_factory=list, max_length=10)
    preferred_languages: list[Literal["en", "bn", "hi"]] = Field(
        default_factory=list, alias="preferredLanguages", max_length=3
    )

    @field_validator("interests")
    @classmethod
    def clean_interests(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 50 for value in cleaned):
            raise ValueError("Circle interests must contain between 1 and 50 characters")
        normalized = list(dict.fromkeys(value.casefold() for value in cleaned))
        if len(normalized) != len(cleaned):
            raise ValueError("Circle interests must be unique")
        return cleaned


class CircleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    suggestion_rules: CircleSuggestionRules = Field(
        default_factory=CircleSuggestionRules, alias="suggestionRules"
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Circle name is too short")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CircleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    suggestion_rules: CircleSuggestionRules | None = Field(default=None, alias="suggestionRules")
    active: bool | None = None

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one circle field must be supplied")
        if "name" in self.model_fields_set:
            if self.name is None or len(self.name.strip()) < 2:
                raise ValueError("Circle name is too short")
            self.name = self.name.strip()
        if "description" in self.model_fields_set and self.description is not None:
            self.description = self.description.strip() or None
        if "suggestion_rules" in self.model_fields_set and self.suggestion_rules is None:
            raise ValueError("Suggestion rules cannot be null")
        if "active" in self.model_fields_set and self.active is None:
            raise ValueError("Active cannot be null")
        return self


class CircleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    name: str
    description: str | None = None
    active: bool
    suggestion_rules: CircleSuggestionRules = Field(alias="suggestionRules")
    joined: bool
    selected_by_user: bool | None = Field(default=None, alias="selectedByUser")
    suggested: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class CircleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    max_memberships: int = Field(alias="maxMemberships", ge=1, le=20)
    updated_at: datetime = Field(alias="updatedAt")


class CircleSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    max_memberships: int = Field(alias="maxMemberships", ge=1, le=20)


def is_suggested(rules: CircleSuggestionRules, interests: list[str], language: str | None) -> bool:
    """An empty rule is general; otherwise any approved rule may recommend it."""

    if not rules.interests and not rules.preferred_languages:
        return True
    member_interests = {value.strip().casefold() for value in interests if value.strip()}
    rule_interests = {value.casefold() for value in rules.interests}
    return bool(member_interests & rule_interests) or language in rules.preferred_languages
