"""Alembic environment.

Async, because the application's engine is async and running migrations through
a second, synchronous driver would mean maintaining two sets of connection
settings that can disagree.

The database URL comes from ``Settings``, not from ``alembic.ini`` — so there is
exactly one definition of how to reach the database, and the password is never
written to a committed file or echoed into Alembic's log output.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from ssa.infrastructure.database import models  # noqa: F401  (populates metadata)
from ssa.infrastructure.database.base import Base
from ssa.infrastructure.database.engine import create_database_engine
from ssa.shared.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = Settings.load()


def _configure(**kwargs: object) -> None:
    """Shared Alembic configuration for both offline and online modes.

    ``compare_type`` and ``compare_server_default`` are on because without them
    autogenerate silently ignores a changed column type or default — producing
    an empty migration that looks like "no changes needed".
    """
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        render_as_batch=False,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to review exactly what a migration will do before it touches a real
    database — which is the review gate for this phase.
    """
    _configure(
        url=settings.db.url.render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    engine = create_database_engine(settings.db)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
