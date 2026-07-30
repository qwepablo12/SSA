"""``/history`` — list the user's most recent completed study sessions.

Thin: resolves the Telegram sender, calls ``GetStudyHistory``, and renders
each entry as one line. Which sessions qualify, their ordering and the row
cap all live in the use case (02_Project_Structure.md §9 step 7); converting
each timestamp to the user's own timezone for display is presentation, not a
business rule, so it stays here.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from ssa.application.tracking.dto import GetStudyHistoryRequest, StudyHistoryEntry
from ssa.application.tracking.use_cases.get_study_history import GetStudyHistory
from ssa.domain.identity.repositories import UserRepository

__all__ = ["router"]

router = Router(name="history")

_NOT_ONBOARDED = "Send /start first so I know who you are."
_EMPTY = "You haven't completed any study sessions yet. Send /study to start one."


@router.message(Command("history"))
async def handle_history(
    message: Message,
    get_study_history: FromDishka[GetStudyHistory],
    users: FromDishka[UserRepository],
) -> None:
    user = await users.find_by_telegram_id(message.from_user.id) if message.from_user else None
    if user is None or user.id is None:
        await message.answer(_NOT_ONBOARDED)
        return

    result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user.id))
    if not result.entries:
        await message.answer(_EMPTY)
        return

    tz = ZoneInfo(user.timezone)
    lines = [_format_entry(entry, tz) for entry in result.entries]
    await message.answer("\n".join(lines))


def _format_entry(entry: StudyHistoryEntry, tz: ZoneInfo) -> str:
    subject = entry.subject_name or "General"
    when = entry.ended_at.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    line = f"{when} — {subject} — {entry.duration_minutes} min"
    if entry.focus_score is not None:
        line += f" — focus {entry.focus_score}/5"
    return line
