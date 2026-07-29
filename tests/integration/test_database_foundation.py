"""Integration tests for the database foundation.

Requires a running PostgreSQL (``make up``). Marked so the fast suite can skip
them: ``pytest -m "not integration"``.

These tests use the ``engine`` fixture rather than the transaction-wrapped
``session`` fixture, because what is under test *is* transaction behaviour —
wrapping it in an outer transaction would test the harness instead. They create
and drop their own scratch tables, in ``finally`` blocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ssa.domain.common.errors import ConflictError
from ssa.infrastructure.database.engine import create_session_factory
from ssa.infrastructure.database.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


class TestConnectivity:
    async def test_engine_connects(self, engine: AsyncEngine) -> None:
        async with engine.connect() as conn:
            assert (await conn.scalar(text("SELECT 1"))) == 1

    async def test_server_is_postgres_16_or_newer(self, engine: AsyncEngine) -> None:
        async with engine.connect() as conn:
            version = await conn.scalar(text("SHOW server_version_num"))
        assert int(str(version)) >= 160000

    async def test_gen_random_uuid_is_available_without_an_extension(
        self, engine: AsyncEngine
    ) -> None:
        """``PublicUUID`` relies on this being built in (PostgreSQL 13+)."""
        async with engine.connect() as conn:
            value = await conn.scalar(text("SELECT gen_random_uuid()"))
        assert value is not None

    async def test_driver_returns_aware_datetimes(self, session: AsyncSession) -> None:
        """A naive datetime from the driver would corrupt every local_date
        derivation downstream (06 §15)."""
        now = await session.scalar(text("SELECT now()"))
        assert now is not None
        assert now.tzinfo is not None


@pytest_asyncio.fixture
async def probe_table(engine: AsyncEngine) -> AsyncIterator[str]:
    """A real (non-temporary) scratch table.

    Temporary tables are scoped to a single connection, which would make a
    cross-transaction visibility test pass vacuously — it would be asserting
    that a temp table is invisible to another connection, not that a rollback
    happened.
    """
    name = "_uow_probe"
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        await conn.execute(text(f"CREATE TABLE {name} (n integer NOT NULL)"))
    try:
        yield name
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))


@pytest_asyncio.fixture
async def deferred_unique_table(engine: AsyncEngine) -> AsyncIterator[str]:
    """A table whose unique constraint is checked at COMMIT, not at INSERT.

    This is what makes it possible to test that :meth:`commit` translates an
    ``IntegrityError``. With an immediate constraint the error surfaces from
    ``execute()`` instead, which is a different code path.
    """
    name = "_uow_deferred"
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        await conn.execute(
            text(
                f"CREATE TABLE {name} ("
                "  n integer NOT NULL,"
                f"  CONSTRAINT uq_{name}_n UNIQUE (n) DEFERRABLE INITIALLY DEFERRED"
                ")"
            )
        )
    try:
        yield name
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))


class TestUnitOfWork:
    async def test_commit_persists(self, engine: AsyncEngine, probe_table: str) -> None:
        factory = create_session_factory(engine)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await uow.session.execute(text(f"INSERT INTO {probe_table} VALUES (1)"))
            await uow.commit()

        async with engine.connect() as conn:
            assert (await conn.scalar(text(f"SELECT count(*) FROM {probe_table}"))) == 1

    async def test_exiting_without_commit_rolls_back(
        self, engine: AsyncEngine, probe_table: str
    ) -> None:
        """The safe default: a forgotten commit writes nothing, not half."""
        factory = create_session_factory(engine)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await uow.session.execute(text(f"INSERT INTO {probe_table} VALUES (42)"))
            # deliberately no commit

        async with engine.connect() as conn:
            assert (await conn.scalar(text(f"SELECT count(*) FROM {probe_table}"))) == 0

    async def test_exception_inside_the_block_rolls_back(
        self, engine: AsyncEngine, probe_table: str
    ) -> None:
        factory = create_session_factory(engine)
        with pytest.raises(RuntimeError, match="boom"):
            async with SqlAlchemyUnitOfWork(factory) as uow:
                await uow.session.execute(text(f"INSERT INTO {probe_table} VALUES (7)"))
                await uow.commit()
                raise RuntimeError("boom")

        # The commit happened before the exception, so it stands. This documents
        # that the unit of work does not undo an explicit commit — the use case
        # owns that decision.
        async with engine.connect() as conn:
            assert (await conn.scalar(text(f"SELECT count(*) FROM {probe_table}"))) == 1

    async def test_integrity_error_at_commit_becomes_a_domain_error(
        self, engine: AsyncEngine, deferred_unique_table: str
    ) -> None:
        """No sqlalchemy exception may escape into the application layer."""
        factory = create_session_factory(engine)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await uow.session.execute(text(f"INSERT INTO {deferred_unique_table} VALUES (1)"))
            await uow.session.execute(text(f"INSERT INTO {deferred_unique_table} VALUES (1)"))
            with pytest.raises(ConflictError) as caught:
                await uow.commit()

        # The constraint name is only usable because of the naming convention in
        # base.py — this is what makes that convention load-bearing rather than
        # cosmetic.
        assert caught.value.details["constraint"] == f"uq_{deferred_unique_table}_n"

    async def test_is_not_reentrant(self, engine: AsyncEngine) -> None:
        factory = create_session_factory(engine)
        uow = SqlAlchemyUnitOfWork(factory)
        async with uow:
            with pytest.raises(RuntimeError, match="not re-entrant"):
                await uow.__aenter__()

    async def test_session_access_outside_the_context_is_a_programming_error(
        self, engine: AsyncEngine
    ) -> None:
        uow = SqlAlchemyUnitOfWork(create_session_factory(engine))
        with pytest.raises(RuntimeError, match="not active"):
            _ = uow.session
