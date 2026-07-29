"""Identity domain entities (06_Database_Schema.md Part I).

``User`` is deliberately Telegram-free (D4) — it must stay meaningful once a
web client exists. ``TelegramAccount`` and ``PrivacySettings`` are 1:1
extension records keyed by ``user_id`` rather than a surrogate id, so unlike
``User`` they do not use the :class:`~ssa.domain.common.entity.Entity`
identity-equality mixin: their key is never "pending" the way a surrogate id
is before insert, so plain dataclass value equality is simpler and just as
correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import available_timezones

from ssa.domain.common.entity import Entity
from ssa.domain.common.errors import ValidationError
from ssa.domain.identity.enums import UserStatus, Visibility

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["PrivacySettings", "TelegramAccount", "User"]

# Computed once at import time: the picker list is fixed, and computing this
# per validation would mean walking the IANA database on every call.
_VALID_TIMEZONES = available_timezones()


def _validate_timezone(timezone: str) -> None:
    if timezone not in _VALID_TIMEZONES:
        raise ValidationError("Unknown IANA timezone", timezone=timezone)


@dataclass(eq=False)
class User(Entity):
    """The internal identity record. Every other table points here (06 §2)."""

    public_id: uuid.UUID
    timezone: str
    locale: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    display_name: str | None = None
    onboarding_completed_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_timezone(self.timezone)
        if self.display_name is not None and not (1 <= len(self.display_name) <= 64):
            raise ValidationError(
                "display_name must be 1-64 characters", display_name=self.display_name
            )

    def change_timezone(self, timezone: str) -> None:
        """Update the IANA timezone.

        Past ``local_date`` values on tracking records are never rewritten
        (06 §15.7) — only records written after this call see the new zone.
        """
        _validate_timezone(timezone)
        self.timezone = timezone

    def complete_onboarding(self, *, at: datetime) -> None:
        self.onboarding_completed_at = at

    def mark_deleted(self, *, at: datetime) -> None:
        self.status = UserStatus.DELETED
        self.deleted_at = at


@dataclass
class TelegramAccount:
    """Telegram-specific identity, isolated so a second login provider is a
    new table rather than a schema-wide migration (06 §3, D4)."""

    user_id: int
    telegram_id: int
    chat_id: int
    linked_at: datetime
    telegram_username: str | None = None
    language_code: str | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.telegram_id <= 0:
            raise ValidationError("telegram_id must be positive", telegram_id=self.telegram_id)
        if self.telegram_username is not None and len(self.telegram_username) > 32:
            raise ValidationError(
                "telegram_username must be at most 32 characters",
                telegram_username=self.telegram_username,
            )

    def record_activity(self, *, at: datetime) -> None:
        self.last_seen_at = at


@dataclass
class PrivacySettings:
    """Per-user privacy and consent state, present from the first user row
    even though social features are out of scope for this slice (06 §4)."""

    user_id: int
    updated_at: datetime
    profile_visibility: Visibility = Visibility.PRIVATE
    stats_visibility: Visibility = Visibility.PRIVATE
    leaderboard_opt_in: bool = False
    research_consent: bool = False
    research_consent_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.research_consent and self.research_consent_at is None:
            raise ValidationError("research_consent_at is required once consent is granted")

    def grant_research_consent(self, *, at: datetime) -> None:
        self.research_consent = True
        self.research_consent_at = at

    def revoke_research_consent(self) -> None:
        self.research_consent = False
        self.research_consent_at = None
