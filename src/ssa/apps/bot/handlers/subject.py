"""``/subject`` — manage a user's study subjects.

Thin: parses the ``add <name>`` sub-command, calls ``CreateSubject``,
translates its expected failure modes into text. Naming rules, duplicate
detection and the transaction boundary all live in the use case
(02_Project_Structure.md §9 step 7).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from ssa.application.tracking.dto import CreateSubjectRequest
from ssa.application.tracking.use_cases.create_subject import CreateSubject
from ssa.domain.common.errors import ConflictError, ValidationError
from ssa.domain.identity.repositories import UserRepository

__all__ = ["router"]

router = Router(name="subject")

_NOT_ONBOARDED = "Send /start first so I know who you are."
_USAGE = "Usage: /subject add <name>, e.g. /subject add Math."


@router.message(Command("subject"))
async def handle_subject(
    message: Message,
    command: CommandObject,
    create_subject: FromDishka[CreateSubject],
    users: FromDishka[UserRepository],
) -> None:
    user = await users.find_by_telegram_id(message.from_user.id) if message.from_user else None
    if user is None or user.id is None:
        await message.answer(_NOT_ONBOARDED)
        return

    args = command.args.strip() if command.args else ""
    subcommand, _, rest = args.partition(" ")
    if subcommand.lower() != "add" or not rest.strip():
        await message.answer(_USAGE)
        return

    name = rest.strip()
    try:
        result = await create_subject.execute(CreateSubjectRequest(user_id=user.id, name=name))
    except ConflictError:
        await message.answer(f"You already have a subject called '{name}'.")
        return
    except ValidationError as err:
        await message.answer(f"Couldn't add that subject: {err.message}")
        return

    await message.answer(f"Added subject '{result.name}'.")
