"""Shared test fixtures.

Two rules this harness enforces:

* Integration tests run against a **real PostgreSQL**, never SQLite. Half the
  schema — partial indexes, generated columns, ``TIMESTAMPTZ`` semantics — does
  not exist in SQLite, so a passing SQLite suite would prove nothing about the
  constraints that carry the design.
* Every test runs inside a transaction that is rolled back afterwards, so no
  test can see another test's rows.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ssa.infrastructure.database.engine import create_database_engine
from ssa.shared.settings import DatabaseSettings, Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _test_database_settings() -> DatabaseSettings:
    """Configuration for the throwaway test database.

    Falls back to a conventional local default so a fresh clone can run
    ``make up && make test`` without writing a ``.env`` first.
    """
    settings = Settings.load()
    if settings.test_db is not None:
        return settings.test_db
    return DatabaseSettings(
        host=os.getenv("SSA_TEST_DB__HOST", settings.db.host),
        port=int(os.getenv("SSA_TEST_DB__PORT", str(settings.db.port))),
        user=os.getenv("SSA_TEST_DB__USER", settings.db.user),
        password=settings.db.password,
        name=os.getenv("SSA_TEST_DB__NAME", "ssa_test"),
    )


@pytest.fixture(scope="session")
def test_db_settings() -> DatabaseSettings:
    db = _test_database_settings()
    # A guard, not a nicety: the harness truncates whatever it connects to.
    assert db.name.endswith("_test"), (
        f"refusing to run tests against {db.name!r}: the test database name must end in '_test'"
    )
    return db


def _migrate_test_database_to_head(settings: DatabaseSettings) -> None:
    """Apply every migration to the test database before any integration
    test runs.

    ``make test`` documents ``make up`` as its only prerequisite — a fresh
    clone should not also need a separate manual ``alembic upgrade`` invoked
    against a database most contributors don't even know exists. Alembic's
    own ``env.py`` always builds its engine from ``Settings.load().db``, so
    the only way to point a single ``command.upgrade()`` call at the *test*
    database without duplicating its connection logic is to swap the
    ``SSA_DB__*`` environment variables for the duration of the call.
    """
    overrides = {
        "SSA_DB__HOST": settings.host,
        "SSA_DB__PORT": str(settings.port),
        "SSA_DB__USER": settings.user,
        "SSA_DB__PASSWORD": settings.password.get_secret_value(),
        "SSA_DB__NAME": settings.name,
    }
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest_asyncio.fixture(scope="session")
async def engine(test_db_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    # Off the event loop: env.py's online path is `asyncio.run(...)`, which
    # cannot be nested inside the loop this fixture is already running on.
    await asyncio.to_thread(_migrate_test_database_to_head, test_db_settings)
    engine = create_database_engine(test_db_settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session bound to a transaction that is always rolled back.

    The session joins an outer transaction on a dedicated connection, so
    ``commit()`` inside the code under test commits to a savepoint rather than
    to the database. Real commit semantics, zero persistence.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        db_session = factory()
        try:
            yield db_session
        finally:
            await db_session.close()
            await transaction.rollback()
