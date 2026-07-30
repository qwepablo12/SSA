"""DTOs crossing the identity application boundary (02_Project_Structure.md
§3) — plain data in, plain data out. Domain entities never reach a handler
and ORM models never reach the application layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from ssa.domain.identity.enums import UserStatus, Visibility

__all__ = [
    "LinkTelegramAccountRequest",
    "LinkTelegramAccountResult",
    "OnboardUserRequest",
    "OnboardUserResult",
    "RegisterUserRequest",
    "RegisterUserResult",
    "UpdatePrivacySettingsRequest",
    "UpdatePrivacySettingsResult",
]


class RegisterUserRequest(BaseModel):
    timezone: str
    locale: str = "en"
    display_name: str | None = None


class RegisterUserResult(BaseModel):
    user_id: int
    public_id: uuid.UUID
    status: UserStatus


class LinkTelegramAccountRequest(BaseModel):
    user_id: int
    telegram_id: int
    chat_id: int
    telegram_username: str | None = None
    language_code: str | None = None


class LinkTelegramAccountResult(BaseModel):
    user_id: int
    telegram_id: int
    linked_at: datetime


class OnboardUserRequest(BaseModel):
    """What the bot's ``/start`` handler actually has on hand — no
    ``timezone``: Telegram's message payload never carries one, so
    ``OnboardUser`` supplies a default until a later step lets the user set
    a real one."""

    telegram_id: int
    chat_id: int
    telegram_username: str | None = None
    language_code: str | None = None
    display_name: str | None = None


class OnboardUserResult(BaseModel):
    user_id: int
    public_id: uuid.UUID
    is_new_user: bool


class UpdatePrivacySettingsRequest(BaseModel):
    """Any field left ``None`` is left unchanged — a partial update."""

    user_id: int
    profile_visibility: Visibility | None = None
    stats_visibility: Visibility | None = None
    leaderboard_opt_in: bool | None = None
    research_consent: bool | None = None


class UpdatePrivacySettingsResult(BaseModel):
    user_id: int
    profile_visibility: Visibility
    stats_visibility: Visibility
    leaderboard_opt_in: bool
    research_consent: bool
    research_consent_at: datetime | None
