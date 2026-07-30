"""``/start`` handler.

Thin by design: extracts fields from the Telegram message, calls
``OnboardUser``, and renders one of two fixed replies. Every decision —
find-or-create, default timezone, transaction boundary — lives in the use
case (02_Project_Structure.md §9 step 7).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from ssa.application.identity.dto import OnboardUserRequest
from ssa.application.identity.use_cases.onboard_user import OnboardUser

__all__ = ["router"]

router = Router(name="start")

_WELCOME_NEW = (
    "Hi! I'm the Student Success Assistant. I'll help you track study "
    "sessions and wellbeing without rewarding overwork. You're all set — "
    "more to come soon."
)
_WELCOME_BACK = "Welcome back! You're already set up."


@router.message(CommandStart())
async def handle_start(message: Message, onboard_user: FromDishka[OnboardUser]) -> None:
    if message.from_user is None:
        # Telegram omits `from_user` for channel posts; `/start` never
        # arrives that way, but the field is typed `User | None`.
        return

    result = await onboard_user.execute(
        OnboardUserRequest(
            telegram_id=message.from_user.id,
            chat_id=message.chat.id,
            telegram_username=message.from_user.username,
            language_code=message.from_user.language_code,
            display_name=message.from_user.first_name,
        )
    )

    await message.answer(_WELCOME_NEW if result.is_new_user else _WELCOME_BACK)
