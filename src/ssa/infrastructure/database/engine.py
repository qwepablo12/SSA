"""Async engine and session factory construction.

Both are ``APP``-scoped: created once per process and injected. Creating an
engine per request would open a new connection pool per request, which is a
performance bug that looks like a database problem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from ssa.shared.settings import DatabaseSettings

__all__ = ["create_database_engine", "create_session_factory"]


def create_database_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build the async engine.

    ``pool_pre_ping`` costs one trivial round trip per checkout and removes the
    entire class of "connection was closed by the server overnight" errors that
    otherwise surface as a failed first request each morning.
    """
    return create_async_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory.

    ``expire_on_commit=False`` is not optional under asyncio. With the default,
    touching any attribute after ``commit()`` triggers a lazy refresh, and a
    lazy refresh in async SQLAlchemy raises ``MissingGreenlet`` rather than
    quietly issuing a query. Since use cases routinely read from an object they
    have just committed, the default turns correct-looking code into a runtime
    error.

    ``autoflush=False`` is deliberate too: implicit flushes make it ambiguous
    when a statement is actually sent, which matters when a repository is
    reasoning about constraint violations. Repositories flush explicitly.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
