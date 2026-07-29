"""SQLAlchemy implementation of
:class:`~ssa.domain.tracking.repositories.StudySessionRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ssa.domain.common.errors import NotFoundError
from ssa.domain.tracking.enums import SessionStatus
from ssa.infrastructure.database import models
from ssa.infrastructure.database.mappers.tracking import (
    new_study_session_model,
    update_study_session_model,
)
from ssa.infrastructure.database.mappers.tracking import study_session_to_domain as _to_domain

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.tracking.entities import StudySession

__all__ = ["SqlAlchemyStudySessionRepository"]


class SqlAlchemyStudySessionRepository:
    """Implements
    :class:`~ssa.domain.tracking.repositories.StudySessionRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: StudySession) -> None:
        model = new_study_session_model(session)
        self._session.add(model)
        await self._session.flush()
        session.id = model.id

    async def get_by_id(self, session_id: int) -> StudySession:
        model = await self._session.get(models.StudySession, session_id)
        if model is None:
            raise NotFoundError("Study session not found", session_id=session_id)
        return _to_domain(model)

    async def find_by_id(self, session_id: int) -> StudySession | None:
        model = await self._session.get(models.StudySession, session_id)
        return _to_domain(model) if model is not None else None

    async def find_active_for_user(self, user_id: int) -> StudySession | None:
        model = await self._session.scalar(
            select(models.StudySession).where(
                models.StudySession.user_id == user_id,
                models.StudySession.status == SessionStatus.IN_PROGRESS.value,
            )
        )
        return _to_domain(model) if model is not None else None

    async def list_for_user(
        self, user_id: int, *, since: date | None = None, until: date | None = None
    ) -> list[StudySession]:
        stmt = select(models.StudySession).where(
            models.StudySession.user_id == user_id,
            models.StudySession.deleted_at.is_(None),
        )
        if since is not None:
            stmt = stmt.where(models.StudySession.local_date >= since)
        if until is not None:
            stmt = stmt.where(models.StudySession.local_date <= until)
        stmt = stmt.order_by(models.StudySession.started_at.desc())
        result = await self._session.scalars(stmt)
        return [_to_domain(model) for model in result]

    async def update(self, session: StudySession) -> None:
        model = await self._session.get(models.StudySession, session.id)
        if model is None:
            raise NotFoundError("Study session not found", session_id=session.id)
        update_study_session_model(session, model)
