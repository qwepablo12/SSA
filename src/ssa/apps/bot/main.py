"""Dispatcher setup and long-polling runner (02_Project_Structure.md §5).

Webhook mode is a later step (02_Project_Structure.md §9) — this wires
``Bot``, ``Dispatcher``, routers, the Dishka container, and startup/shutdown
hooks, enough to answer ``/start`` through a real use case.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dishka import make_async_container
from dishka.integrations.aiogram import setup_dishka
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ssa.application.common.di import ApplicationProvider
from ssa.apps.bot.handlers import router
from ssa.infrastructure.database.engine import create_database_engine, create_session_factory
from ssa.infrastructure.di import InfrastructureProvider
from ssa.shared.settings import Settings

if TYPE_CHECKING:
    from dishka import AsyncContainer

__all__ = ["create_dispatcher", "main", "run"]

logger = structlog.get_logger(__name__)


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    await logger.ainfo("bot_started", username=me.username)


async def on_shutdown(bot: Bot) -> None:
    await logger.ainfo("bot_stopped")


def create_dispatcher(container: AsyncContainer) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    # `auto_inject=True` lets a handler declare a use case as
    # `FromDishka[SomeUseCase]` and receive it without an explicit `@inject`
    # on every handler function. One child container is opened per update
    # (dishka's REQUEST scope), matching "one update = one session = one
    # commit" (01_Architecture.md §7.1).
    setup_dishka(container=container, router=dispatcher, auto_inject=True)
    return dispatcher


async def main() -> None:
    settings = Settings.load()
    if settings.bot is None:
        raise RuntimeError(
            "Telegram bot token is not configured — set SSA_BOT__TOKEN (see .env.example)."
        )

    engine = create_database_engine(settings.db)
    session_factory = create_session_factory(engine)
    container = make_async_container(
        InfrastructureProvider(),
        ApplicationProvider(),
        context={async_sessionmaker[AsyncSession]: session_factory},
    )

    bot = Bot(
        token=settings.bot.token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = create_dispatcher(container)

    try:
        # start_polling() already closes the bot session in its own `finally`
        # (close_bot_session=True by default), after emit_shutdown — closing
        # it again here would be redundant.
        await dispatcher.start_polling(bot)
    finally:
        await container.close()
        await engine.dispose()


def run() -> None:
    asyncio.run(main())
