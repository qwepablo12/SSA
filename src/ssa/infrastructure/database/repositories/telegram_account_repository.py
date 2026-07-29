"""SQLAlchemy implementation of
:class:`~ssa.domain.identity.repositories.TelegramAccountRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from ssa.domain.common.errors import NotFoundError
from ssa.infrastructure.database import models
from ssa.infrastructure.database.errors import conflict_from_integrity_error
from ssa.infrastructure.database.mappers.identity import (
    new_telegram_account_model,
    update_telegram_account_model,
)
from ssa.infrastructure.database.mappers.identity import (
    telegram_account_to_domain as _to_domain,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.identity.entities import TelegramAccount

__all__ = ["SqlAlchemyTelegramAccountRepository"]


class SqlAlchemyTelegramAccountRepository:
    """Implements
    :class:`~ssa.domain.identity.repositories.TelegramAccountRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, account: TelegramAccount) -> None:
        self._session.add(new_telegram_account_model(account))
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise conflict_from_integrity_error(err) from err

    async def get_by_user_id(self, user_id: int) -> TelegramAccount:
        model = await self._session.get(models.TelegramAccount, user_id)
        if model is None:
            raise NotFoundError("Telegram account not found", user_id=user_id)
        return _to_domain(model)

    async def find_by_user_id(self, user_id: int) -> TelegramAccount | None:
        model = await self._session.get(models.TelegramAccount, user_id)
        return _to_domain(model) if model is not None else None

    async def update(self, account: TelegramAccount) -> None:
        model = await self._session.get(models.TelegramAccount, account.user_id)
        if model is None:
            raise NotFoundError("Telegram account not found", user_id=account.user_id)
        update_telegram_account_model(account, model)
