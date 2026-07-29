"""SQLAlchemy implementation of the :class:`UnitOfWork` port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ssa.domain.common.errors import ExternalServiceError
from ssa.infrastructure.database.errors import conflict_from_integrity_error

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["SqlAlchemyUnitOfWork"]


class SqlAlchemyUnitOfWork:
    """One transaction, bound to one session, owned by one use case.

    Lifecycle::

        async with uow:
            await service.do_something()   # repositories add / query / flush
            await uow.commit()             # exactly once, by the use case

    Leaving the block without committing rolls back. That is the safe default:
    a forgotten ``commit()`` writes nothing rather than writing half.

    Translation of infrastructure exceptions happens here and in the
    repositories, so that ``sqlalchemy`` types never escape into the application
    layer (01_Architecture.md §7.2).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        """The active session.

        Repositories receive this. Accessing it outside the context is a
        programming error, not a runtime condition, hence the assertion-style
        exception rather than a domain error.
        """
        if self._session is None:
            raise RuntimeError("Unit of work is not active; use `async with uow:`")
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("Unit of work is not re-entrant")
        self._session = self._session_factory()
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:  # pragma: no cover - defensive
            return
        try:
            if exc is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as err:
            await self.session.rollback()
            raise conflict_from_integrity_error(err) from err
        except SQLAlchemyError as err:
            await self.session.rollback()
            raise ExternalServiceError("Database operation failed") from err
        self._committed = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._committed = False

    async def flush(self) -> None:
        """Send pending statements without ending the transaction.

        Used when a use case needs a generated primary key mid-transaction.
        Translates the same way as :meth:`commit`, because a constraint
        violation surfaces here whenever the statement is sent early.
        """
        try:
            await self.session.flush()
        except IntegrityError as err:
            raise conflict_from_integrity_error(err) from err
