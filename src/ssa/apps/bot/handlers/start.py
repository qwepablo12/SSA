"""``/start`` handler.

No business logic: no user lookup, no onboarding branch yet. That arrives
once ``application.identity`` use cases are wired into a middleware
(02_Project_Structure.md §9 step 7 continues into onboarding).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import CommandStart

if TYPE_CHECKING:
    from aiogram.types import Message

__all__ = ["router"]

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        "Hi! I'm the Student Success Assistant. I'll help you track study "
        "sessions and wellbeing without rewarding overwork. More to come soon."
    )
