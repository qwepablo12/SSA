"""SQLAlchemy implementation of
:class:`~ssa.domain.tracking.repositories.MoodLogRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ssa.infrastructure.database import models
from ssa.infrastructure.database.mappers.tracking import mood_log_to_domain as _to_domain
from ssa.infrastructure.database.mappers.tracking import new_mood_log_model

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.tracking.entities import MoodLog

__all__ = ["SqlAlchemyMoodLogRepository"]


class SqlAlchemyMoodLogRepository:
    """Implements :class:`~ssa.domain.tracking.repositories.MoodLogRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: MoodLog) -> None:
        model = new_mood_log_model(log)
        self._session.add(model)
        await self._session.flush()
        log.id = model.id

    async def list_for_user_on_date(self, user_id: int, local_date: date) -> list[MoodLog]:
        stmt = (
            select(models.MoodLog)
            .where(
                models.MoodLog.user_id == user_id,
                models.MoodLog.local_date == local_date,
            )
            .order_by(models.MoodLog.recorded_at.desc())
        )
        result = await self._session.scalars(stmt)
        return [_to_domain(model) for model in result]
