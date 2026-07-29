"""Ports the domain declares and infrastructure implements.

These are the only way the domain and application layers reach the outside
world. Declaring them here — rather than in ``infrastructure`` — is the
dependency inversion that lets the domain be unit-tested with no database, no
event loop, and no mocking library (01_Architecture.md §3).
"""

from __future__ import annotations

from datetime import date, datetime
from types import TracebackType
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

__all__ = ["Clock", "UnitOfWork"]


@runtime_checkable
class Clock(Protocol):
    """Source of the current time.

    Application code never calls ``datetime.now()``. Everything that needs the
    time depends on this, so tests can freeze it — which matters more here than
    in most systems, because streaks, daily rollups and "today" are all
    time-boundary logic and are otherwise untestable without sleeping.
    """

    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        ...

    def today_in(self, timezone: ZoneInfo) -> date:
        """The current local calendar date in ``timezone``.

        Separate from :meth:`now` because "what day is it for this user" is the
        question the domain actually asks, and deriving it at each call site is
        how timezone bugs get in (01_Architecture.md §7.4).
        """
        ...


class UnitOfWork(Protocol):
    """One business transaction.

    Scope rules (01_Architecture.md §7.1):

    * One request / update / job == one unit of work == one commit.
    * The *application service* owns the boundary and calls :meth:`commit`.
    * Repositories never commit and never roll back. They add, query, flush.
    * Exiting the context without committing rolls back. Forgetting to commit
      is therefore a no-op, not a partial write.
    """

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None:
        """Commit the transaction. Called once, by the use case."""
        ...

    async def rollback(self) -> None:
        """Discard all changes made in this unit of work."""
        ...

    async def flush(self) -> None:
        """Send pending statements without committing.

        Needed when a use case requires a generated primary key before the
        transaction ends. Does not end the transaction.
        """
        ...
