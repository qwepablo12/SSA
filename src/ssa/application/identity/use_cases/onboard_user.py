"""``OnboardUser`` — the bot's ``/start`` entrypoint (02_Project_Structure.md
§9 step 7): find-or-create the internal identity behind an inbound Telegram
update.

Composes :class:`~ssa.application.identity.use_cases.register_user.RegisterUser`
and :class:`~ssa.application.identity.use_cases.link_telegram_account.LinkTelegramAccount`
by calling their undecorated ``_execute`` cores directly, so all three steps
join this use case's own transaction instead of each committing separately
(01_Architecture.md §7.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.identity.dto import (
    LinkTelegramAccountRequest,
    OnboardUserResult,
    RegisterUserRequest,
)

if TYPE_CHECKING:
    from ssa.application.identity.dto import OnboardUserRequest
    from ssa.application.identity.use_cases.link_telegram_account import LinkTelegramAccount
    from ssa.application.identity.use_cases.register_user import RegisterUser
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import TelegramAccountRepository, UserRepository

__all__ = ["OnboardUser"]

# Telegram never tells us a user's timezone. Real onboarding into a specific
# zone is a later step (a settings flow); until then every new user gets this
# default rather than the handler inventing one (01_Architecture.md §7.4).
_DEFAULT_TIMEZONE = "UTC"


class OnboardUser:
    """Returns the existing user for a known ``telegram_id`` (touching
    ``TelegramAccount.last_seen_at``), or registers a new one and links the
    Telegram account, all in one transaction."""

    def __init__(
        self,
        *,
        users: UserRepository,
        telegram_accounts: TelegramAccountRepository,
        register_user: RegisterUser,
        link_telegram_account: LinkTelegramAccount,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._telegram_accounts = telegram_accounts
        self._register_user = register_user
        self._link_telegram_account = link_telegram_account
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: OnboardUserRequest) -> OnboardUserResult:
        existing = await self._users.find_by_telegram_id(request.telegram_id)
        if existing is not None:
            if existing.id is None:  # pragma: no cover - defensive; persisted users always have one
                raise RuntimeError("find_by_telegram_id returned a user with no id")
            account = await self._telegram_accounts.get_by_user_id(existing.id)
            account.record_activity(at=self._clock.now())
            await self._telegram_accounts.update(account)
            return OnboardUserResult(
                user_id=existing.id, public_id=existing.public_id, is_new_user=False
            )

        # Use the undecorated implementation so nested operations
        # participate in this transaction instead of committing independently.
        registered = await self._register_user._execute(
            RegisterUserRequest(
                timezone=_DEFAULT_TIMEZONE,
                locale=request.language_code or "en",
                display_name=request.display_name,
            )
        )
        await self._link_telegram_account._execute(
            LinkTelegramAccountRequest(
                user_id=registered.user_id,
                telegram_id=request.telegram_id,
                chat_id=request.chat_id,
                telegram_username=request.telegram_username,
                language_code=request.language_code,
            )
        )
        return OnboardUserResult(
            user_id=registered.user_id, public_id=registered.public_id, is_new_user=True
        )
