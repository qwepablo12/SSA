"""Dispatcher setup and long-polling runner (02_Project_Structure.md §5).

Webhook mode, the DI container, and the onboarding middleware are later
steps (02_Project_Structure.md §9) — this wires just ``Bot``, ``Dispatcher``,
routers, and startup/shutdown hooks, enough to answer ``/start``.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ssa.apps.bot.handlers import router
from ssa.shared.settings import Settings

__all__ = ["create_dispatcher", "main", "run"]

logger = structlog.get_logger(__name__)


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    await logger.ainfo("bot_started", username=me.username)


async def on_shutdown(bot: Bot) -> None:
    await logger.ainfo("bot_stopped")


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    return dispatcher


async def main() -> None:
    settings = Settings.load()
    if settings.bot is None:
        raise RuntimeError(
            "Telegram bot token is not configured — set SSA_BOT__TOKEN (see .env.example)."
        )

    bot = Bot(
        token=settings.bot.token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = create_dispatcher()

    # start_polling() already closes the bot session in its own `finally`
    # (close_bot_session=True by default), after emit_shutdown — closing it
    # again here would be redundant.
    await dispatcher.start_polling(bot)


def run() -> None:
    asyncio.run(main())
