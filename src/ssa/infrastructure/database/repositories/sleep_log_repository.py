"""SQLAlchemy implementation of
:class:`~ssa.domain.tracking.repositories.SleepLogRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ssa.infrastructure.database import models
from ssa.infrastructure.database.mappers.tracking import new_sleep_log_model
from ssa.infrastructure.database.mappers.tracking import sleep_log_to_domain as _to_domain

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.tracking.entities import SleepLog

__all__ = ["SqlAlchemySleepLogRepository"]


class SqlAlchemySleepLogRepository:
    """Implements :class:`~ssa.domain.tracking.repositories.SleepLogRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: SleepLog) -> None:
        model = new_sleep_log_model(log)
        self._session.add(model)
        await self._session.flush()
        log.id = model.id

    async def find_for_user_on_date(self, user_id: int, local_date: date) -> SleepLog | None:
        model = await self._session.scalar(
            select(models.SleepLog).where(
                models.SleepLog.user_id == user_id,
                models.SleepLog.local_date == local_date,
            )
        )
        return _to_domain(model) if model is not None else None
