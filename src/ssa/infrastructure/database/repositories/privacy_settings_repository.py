"""SQLAlchemy implementation of
:class:`~ssa.domain.identity.repositories.PrivacySettingsRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from ssa.domain.common.errors import NotFoundError
from ssa.infrastructure.database import models
from ssa.infrastructure.database.errors import conflict_from_integrity_error
from ssa.infrastructure.database.mappers.identity import (
    new_privacy_settings_model,
    update_privacy_settings_model,
)
from ssa.infrastructure.database.mappers.identity import (
    privacy_settings_to_domain as _to_domain,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ssa.domain.identity.entities import PrivacySettings

__all__ = ["SqlAlchemyPrivacySettingsRepository"]


class SqlAlchemyPrivacySettingsRepository:
    """Implements
    :class:`~ssa.domain.identity.repositories.PrivacySettingsRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, settings: PrivacySettings) -> None:
        self._session.add(new_privacy_settings_model(settings))
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise conflict_from_integrity_error(err) from err

    async def get_by_user_id(self, user_id: int) -> PrivacySettings:
        model = await self._session.get(models.PrivacySettings, user_id)
        if model is None:
            raise NotFoundError("Privacy settings not found", user_id=user_id)
        return _to_domain(model)

    async def find_by_user_id(self, user_id: int) -> PrivacySettings | None:
        model = await self._session.get(models.PrivacySettings, user_id)
        return _to_domain(model) if model is not None else None

    async def update(self, settings: PrivacySettings) -> None:
        model = await self._session.get(models.PrivacySettings, settings.user_id)
        if model is None:
            raise NotFoundError("Privacy settings not found", user_id=settings.user_id)
        update_privacy_settings_model(settings, model)
