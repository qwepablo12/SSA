"""SQLAlchemy implementation of
:class:`~ssa.domain.tracking.repositories.ExerciseLogRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ssa.infrastructure.database import models
from ssa.infrastructure.database.mappers.tracking import exercise_log_to_domain as _to_domain
from ssa.infrastructure.database.mappers.tracking import new_exercise_log_model

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.tracking.entities import ExerciseLog

__all__ = ["SqlAlchemyExerciseLogRepository"]


class SqlAlchemyExerciseLogRepository:
    """Implements
    :class:`~ssa.domain.tracking.repositories.ExerciseLogRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: ExerciseLog) -> None:
        model = new_exercise_log_model(log)
        self._session.add(model)
        await self._session.flush()
        log.id = model.id

    async def list_for_user_on_date(self, user_id: int, local_date: date) -> list[ExerciseLog]:
        stmt = (
            select(models.ExerciseLog)
            .where(
                models.ExerciseLog.user_id == user_id,
                models.ExerciseLog.local_date == local_date,
            )
            .order_by(models.ExerciseLog.occurred_at.desc())
        )
        result = await self._session.scalars(stmt)
        return [_to_domain(model) for model in result]
