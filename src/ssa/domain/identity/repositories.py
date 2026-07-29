"""Repository protocols for the identity module (02_Project_Structure.md §2).

Declared in the domain and implemented in
``infrastructure/database/repositories`` — this inversion is what lets
``application`` depend on ``domain`` alone and never on SQLAlchemy directly.
Method names follow the repository convention (02 §8): ``get_by_*`` raises
:class:`~ssa.domain.common.errors.NotFoundError`, ``find_by_*`` returns
``None``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid

    from ssa.domain.identity.entities import PrivacySettings, TelegramAccount, User

__all__ = ["PrivacySettingsRepository", "TelegramAccountRepository", "UserRepository"]


class UserRepository(Protocol):
    """Persistence port for :class:`~ssa.domain.identity.entities.User`."""

    async def add(self, user: User) -> None:
        """Insert a new user and assign the generated ``user.id``."""
        ...

    async def get_by_id(self, user_id: int) -> User: ...

    async def find_by_id(self, user_id: int) -> User | None: ...

    async def find_by_public_id(self, public_id: uuid.UUID) -> User | None: ...

    async def find_by_telegram_id(self, telegram_id: int) -> User | None:
        """The bot's primary lookup: an inbound Telegram update to the
        internal user it belongs to (02 §5, ``apps/bot/middlewares/user.py``)."""
        ...

    async def update(self, user: User) -> None:
        """Persist changes made through the entity's own mutator methods."""
        ...


class TelegramAccountRepository(Protocol):
    """Persistence port for
    :class:`~ssa.domain.identity.entities.TelegramAccount`.

    Keyed by ``user_id`` rather than a surrogate id, matching the 1:1 table
    (06 §3).
    """

    async def add(self, account: TelegramAccount) -> None: ...

    async def get_by_user_id(self, user_id: int) -> TelegramAccount: ...

    async def find_by_user_id(self, user_id: int) -> TelegramAccount | None: ...

    async def update(self, account: TelegramAccount) -> None: ...


class PrivacySettingsRepository(Protocol):
    """Persistence port for
    :class:`~ssa.domain.identity.entities.PrivacySettings`. Same
    keyed-by-``user_id`` reasoning as :class:`TelegramAccountRepository`."""

    async def add(self, settings: PrivacySettings) -> None: ...

    async def get_by_user_id(self, user_id: int) -> PrivacySettings: ...

    async def find_by_user_id(self, user_id: int) -> PrivacySettings | None: ...

    async def update(self, settings: PrivacySettings) -> None: ...
