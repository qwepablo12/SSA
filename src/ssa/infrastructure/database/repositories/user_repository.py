"""SQLAlchemy implementation of :class:`~ssa.domain.identity.repositories.UserRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ssa.domain.common.errors import NotFoundError
from ssa.infrastructure.database import models
from ssa.infrastructure.database.errors import conflict_from_integrity_error
from ssa.infrastructure.database.mappers.identity import new_user_model, update_user_model
from ssa.infrastructure.database.mappers.identity import user_to_domain as _to_domain

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.identity.entities import User

__all__ = ["SqlAlchemyUserRepository"]


class SqlAlchemyUserRepository:
    """Implements :class:`~ssa.domain.identity.repositories.UserRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        model = new_user_model(user)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise conflict_from_integrity_error(err) from err
        user.id = model.id

    async def get_by_id(self, user_id: int) -> User:
        model = await self._session.get(models.User, user_id)
        if model is None:
            raise NotFoundError("User not found", user_id=user_id)
        return _to_domain(model)

    async def find_by_id(self, user_id: int) -> User | None:
        model = await self._session.get(models.User, user_id)
        return _to_domain(model) if model is not None else None

    async def find_by_public_id(self, public_id: uuid.UUID) -> User | None:
        model = await self._session.scalar(
            select(models.User).where(models.User.public_id == public_id)
        )
        return _to_domain(model) if model is not None else None

    async def find_by_telegram_id(self, telegram_id: int) -> User | None:
        model = await self._session.scalar(
            select(models.User)
            .join(models.TelegramAccount, models.TelegramAccount.user_id == models.User.id)
            .where(models.TelegramAccount.telegram_id == telegram_id)
        )
        return _to_domain(model) if model is not None else None

    async def update(self, user: User) -> None:
        model = await self._session.get(models.User, user.id)
        if model is None:
            raise NotFoundError("User not found", user_id=user.id)
        update_user_model(user, model)
