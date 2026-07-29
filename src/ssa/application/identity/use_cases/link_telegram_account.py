"""``LinkTelegramAccount`` — attach Telegram-specific identity to an existing
``User`` (06_Database_Schema.md §3, D4). Kept separate from
:class:`~ssa.application.identity.use_cases.register_user.RegisterUser` so a
second login provider is a new use case, not a rewrite of this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.identity.dto import LinkTelegramAccountResult
from ssa.domain.identity.entities import TelegramAccount

if TYPE_CHECKING:
    from ssa.application.identity.dto import LinkTelegramAccountRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import TelegramAccountRepository, UserRepository

__all__ = ["LinkTelegramAccount"]


class LinkTelegramAccount:
    """Fails with :class:`~ssa.domain.common.errors.NotFoundError` if
    ``user_id`` does not name an existing user, and with
    :class:`~ssa.domain.common.errors.ConflictError` if this user already has
    a linked account or ``telegram_id`` is already linked elsewhere — both are
    invariants the database enforces structurally (``telegram_accounts`` is
    keyed by ``user_id`` and ``telegram_id`` is unique)."""

    def __init__(
        self,
        *,
        users: UserRepository,
        telegram_accounts: TelegramAccountRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._telegram_accounts = telegram_accounts
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: LinkTelegramAccountRequest) -> LinkTelegramAccountResult:
        user = await self._users.get_by_id(request.user_id)
        if user.id is None:  # pragma: no cover - defensive; get_by_id only returns persisted users
            raise RuntimeError("UserRepository.get_by_id returned a user with no id")

        linked_at = self._clock.now()
        account = TelegramAccount(
            user_id=user.id,
            telegram_id=request.telegram_id,
            chat_id=request.chat_id,
            telegram_username=request.telegram_username,
            language_code=request.language_code,
            linked_at=linked_at,
        )
        await self._telegram_accounts.add(account)

        return LinkTelegramAccountResult(
            user_id=account.user_id, telegram_id=account.telegram_id, linked_at=linked_at
        )
