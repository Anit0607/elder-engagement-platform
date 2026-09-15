"""Member-controlled notification preferences and delivery-window policy."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from app.profiles import NotificationWindow


class NotificationPreferencesUpdate(BaseModel):
    """A complete replacement prevents ambiguous partial preference changes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    event_reminders: bool = Field(alias="eventReminders")
    content_updates: bool = Field(alias="contentUpdates")
    delivery_window: NotificationWindow = Field(alias="deliveryWindow")


class NotificationPreferences(NotificationPreferencesUpdate):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    updated_at: datetime = Field(alias="updatedAt")


def delivery_is_allowed(
    preferences: NotificationPreferences,
    category: Literal["event", "content"],
    moment: datetime,
) -> bool:
    """Apply category choices and an optional local-time delivery window."""

    if moment.utcoffset() is None:
        raise ValueError("Delivery-policy time must be timezone-aware")
    if category not in {"event", "content"}:
        raise ValueError("Unknown notification category")
    if category == "event" and not preferences.event_reminders:
        return False
    if category == "content" and not preferences.content_updates:
        return False
    window = preferences.delivery_window
    if not window.enabled:
        return True
    try:
        local = moment.astimezone(ZoneInfo(window.time_zone)).time().replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return False
    start = time.fromisoformat(window.start_local_time)
    end = time.fromisoformat(window.end_local_time)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def default_preferences(updated_at: datetime | None = None) -> NotificationPreferences:
    return NotificationPreferences(
        event_reminders=True,
        content_updates=True,
        delivery_window=NotificationWindow(enabled=False, timeZone="Asia/Kolkata"),
        updated_at=updated_at or datetime.now(UTC),
    )
