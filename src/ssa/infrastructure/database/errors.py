"""Translation of ``IntegrityError`` into the domain error hierarchy.

Shared between :class:`~ssa.infrastructure.database.uow.SqlAlchemyUnitOfWork`
and any repository whose ``add()`` flushes eagerly to assign a generated
primary key (``02_Project_Structure.md`` §9 step 4) — a unique or foreign-key
violation surfaces at exactly that flush, so both call sites need the same
translation rather than letting a raw SQLAlchemy exception reach the
application layer (01_Architecture.md §7.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.domain.common.errors import ConflictError

if TYPE_CHECKING:
    from sqlalchemy.exc import IntegrityError

__all__ = ["conflict_from_integrity_error", "constraint_name"]


def constraint_name(err: IntegrityError) -> str | None:
    """Best-effort extraction of the violated constraint name.

    asyncpg exposes it on the underlying ``UniqueViolationError``, but
    SQLAlchemy's asyncpg dialect wraps that in its own DBAPI exception before
    it reaches ``err.orig`` — the attribute lives one level deeper, on
    ``err.orig.__cause__``. Callers that need to distinguish *which* invariant
    failed match on this — which is precisely why the naming convention in
    ``base.py`` is not cosmetic.
    """
    original = getattr(err, "orig", None)
    name = getattr(original, "constraint_name", None)
    if name is not None:
        return name
    return getattr(getattr(original, "__cause__", None), "constraint_name", None)


def conflict_from_integrity_error(err: IntegrityError) -> ConflictError:
    return ConflictError("Operation conflicts with existing data", constraint=constraint_name(err))
