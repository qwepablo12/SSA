"""``@transactional`` — marks the single commit point of a use case
(01_Architecture.md §7.1, 02_Project_Structure.md §3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Concatenate, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ssa.domain.common.protocols import UnitOfWork

__all__ = ["transactional"]


class _HasUnitOfWork(Protocol):
    """Structural requirement of :func:`transactional`: the use case owns its
    unit of work as ``self._uow``."""

    _uow: UnitOfWork


def transactional[Self: _HasUnitOfWork, **P, R](
    method: Callable[Concatenate[Self, P], Awaitable[R]],
) -> Callable[Concatenate[Self, P], Awaitable[R]]:
    """Commit ``self._uow`` exactly once after a clean return.

    An exception propagates without committing, so the ``async with uow:``
    block the caller opened rolls back instead — the same "forgetting to
    commit is a no-op, not a partial write" guarantee the unit of work itself
    documents. Nested use cases are called without this decorator so they
    join the caller's transaction rather than committing early.
    """

    async def wrapper(self: Self, /, *args: P.args, **kwargs: P.kwargs) -> R:
        result = await method(self, *args, **kwargs)
        await self._uow.commit()
        return result

    wrapper.__name__ = getattr(method, "__name__", "execute")
    wrapper.__doc__ = method.__doc__
    return wrapper
