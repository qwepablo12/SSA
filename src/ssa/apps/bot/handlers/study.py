"""``/study`` and ``/done`` — start and complete a study session.

Thin: resolve the Telegram sender to an internal user, call the use case,
translate its expected failure modes into text. Every decision — whether a
session is already active, overlap against past sessions, the transaction
boundary — lives in the use cases (02_Project_Structure.md §9 step 7).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from ssa.application.tracking.dto import CompleteStudySessionRequest, StartStudySessionRequest
from ssa.application.tracking.use_cases.complete_study_session import CompleteStudySession
from ssa.application.tracking.use_cases.start_study_session import StartStudySession
from ssa.domain.common.errors import ConflictError, NotFoundError, ValidationError
from ssa.domain.identity.repositories import UserRepository

__all__ = ["router"]

router = Router(name="study")

_NOT_ONBOARDED = "Send /start first so I know who you are."


@router.message(Command("study"))
async def handle_study_start(
    message: Message,
    command: CommandObject,
    start_study_session: FromDishka[StartStudySession],
    users: FromDishka[UserRepository],
) -> None:
    user = await users.find_by_telegram_id(message.from_user.id) if message.from_user else None
    if user is None or user.id is None:
        await message.answer(_NOT_ONBOARDED)
        return

    subject_name = command.args.strip() if command.args and command.args.strip() else None

    try:
        await start_study_session.execute(
            StartStudySessionRequest(user_id=user.id, subject_name=subject_name)
        )
    except ConflictError:
        await message.answer(
            "You already have a study session in progress. Send /done to finish it."
        )
        return
    except NotFoundError:
        await message.answer(
            f"I don't have a subject called '{subject_name}'. Add it first with "
            f"/subject add {subject_name}."
        )
        return

    reply = "Study session started. Send /done when you're finished."
    if subject_name is not None:
        reply = f"Study session started for {subject_name}. Send /done when you're finished."
    await message.answer(reply)


@router.message(Command("done"))
async def handle_study_done(
    message: Message,
    complete_study_session: FromDishka[CompleteStudySession],
    users: FromDishka[UserRepository],
    command: CommandObject,
) -> None:
    user = await users.find_by_telegram_id(message.from_user.id) if message.from_user else None
    if user is None or user.id is None:
        await message.answer(_NOT_ONBOARDED)
        return

    focus_score: int | None = None
    if command.args is not None and command.args.strip():
        try:
            focus_score = int(command.args.strip())
        except ValueError:
            await message.answer("Focus score must be a whole number from 1 to 5, e.g. /done 4.")
            return

    try:
        result = await complete_study_session.execute(
            CompleteStudySessionRequest(user_id=user.id, focus_score=focus_score)
        )
    except NotFoundError:
        await message.answer(
            "You don't have a study session in progress. Send /study to start one."
        )
        return
    except ConflictError:
        await message.answer(
            "That overlaps with a session you already logged, so I didn't save it."
        )
        return
    except ValidationError as err:
        await message.answer(f"Couldn't complete that session: {err.message}")
        return

    await message.answer(f"Nice work! Session logged: {result.duration_minutes} minutes.")
