"""``RegisterUser`` — create a new internal identity (06_Database_Schema.md
§2). Telegram-free by construction (D4): linking a Telegram account is the
separate :class:`~ssa.application.identity.use_cases.link_telegram_account.LinkTelegramAccount`
use case.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.identity.dto import RegisterUserResult
from ssa.domain.identity.entities import PrivacySettings, User
from ssa.domain.identity.enums import UserStatus

if TYPE_CHECKING:
    from ssa.application.identity.dto import RegisterUserRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import PrivacySettingsRepository, UserRepository

__all__ = ["RegisterUser"]


class RegisterUser:
    """Creates the ``User`` row and its default ``PrivacySettings`` row
    together, in one transaction — privacy settings exist from the first
    user row even though social features are out of scope for this slice
    (06 §4)."""

    def __init__(
        self,
        *,
        users: UserRepository,
        privacy_settings: PrivacySettingsRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._privacy_settings = privacy_settings
        self._clock = clock
        self._uow = uow

    async def _execute(self, request: RegisterUserRequest) -> RegisterUserResult:
        """The undecorated core, callable by a nested use case (e.g.
        ``OnboardUser``) so it joins the caller's transaction instead of
        committing on its own (01_Architecture.md §7.1)."""
        now = self._clock.now()
        user = User(
            public_id=uuid.uuid4(),
            timezone=request.timezone,
            locale=request.locale,
            display_name=request.display_name,
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        await self._users.add(user)
        if user.id is None:  # pragma: no cover - defensive; add() always assigns the id
            raise RuntimeError("UserRepository.add did not assign an id")

        settings = PrivacySettings(user_id=user.id, updated_at=now)
        await self._privacy_settings.add(settings)

        return RegisterUserResult(user_id=user.id, public_id=user.public_id, status=user.status)

    @transactional
    async def execute(self, request: RegisterUserRequest) -> RegisterUserResult:
        return await self._execute(request)
