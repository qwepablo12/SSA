"""SQLAlchemy implementation of
:class:`~ssa.domain.tracking.repositories.SubjectRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ssa.domain.common.errors import NotFoundError
from ssa.infrastructure.database import models
from ssa.infrastructure.database.errors import conflict_from_integrity_error
from ssa.infrastructure.database.mappers.tracking import (
    new_subject_model,
    update_subject_model,
)
from ssa.infrastructure.database.mappers.tracking import subject_to_domain as _to_domain

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.tracking.entities import Subject

__all__ = ["SqlAlchemySubjectRepository"]


class SqlAlchemySubjectRepository:
    """Implements :class:`~ssa.domain.tracking.repositories.SubjectRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, subject: Subject) -> None:
        model = new_subject_model(subject)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise conflict_from_integrity_error(err) from err
        subject.id = model.id

    async def get_by_id(self, subject_id: int) -> Subject:
        model = await self._session.get(models.Subject, subject_id)
        if model is None:
            raise NotFoundError("Subject not found", subject_id=subject_id)
        return _to_domain(model)

    async def find_by_id(self, subject_id: int) -> Subject | None:
        model = await self._session.get(models.Subject, subject_id)
        return _to_domain(model) if model is not None else None

    async def list_for_user(self, user_id: int, *, include_archived: bool = False) -> list[Subject]:
        stmt = select(models.Subject).where(models.Subject.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(~models.Subject.is_archived)
        stmt = stmt.order_by(models.Subject.name)
        result = await self._session.scalars(stmt)
        return [_to_domain(model) for model in result]

    async def update(self, subject: Subject) -> None:
        model = await self._session.get(models.Subject, subject.id)
        if model is None:
            raise NotFoundError("Subject not found", subject_id=subject.id)
        update_subject_model(subject, model)
