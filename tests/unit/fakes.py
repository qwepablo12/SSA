"""Hand-rolled in-memory fakes for application-layer unit tests.

No mocking library, matching the project's approach to domain testing: these
are small, real implementations of the domain protocols
(``ssa.domain.*.repositories``, ``ssa.domain.common.protocols``), so a use
case under test runs against genuine (if simplified) behaviour — including
the same invariants a real repository enforces, such as "the query
constraint that would be a unique index" — rather than a mock that only
returns canned values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ssa.domain.common.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    import uuid
    from datetime import date
    from zoneinfo import ZoneInfo

    from ssa.domain.identity.entities import PrivacySettings, TelegramAccount, User
    from ssa.domain.tracking.entities import Subject

__all__ = [
    "FakeClock",
    "FakePrivacySettingsRepository",
    "FakeSubjectRepository",
    "FakeTelegramAccountRepository",
    "FakeUnitOfWork",
    "FakeUserRepository",
]


class FakeClock:
    """Fixed time, so use case tests never depend on wall-clock timing."""

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now if now is not None else datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def today_in(self, timezone: ZoneInfo) -> date:
        return self._now.astimezone(timezone).date()


class FakeUnitOfWork:
    """Records whether ``commit``/``rollback`` were called; nothing to persist."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc is not None and not self.committed:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        pass


class FakeUserRepository:
    """Implements :class:`~ssa.domain.identity.repositories.UserRepository`."""

    def __init__(self) -> None:
        self._by_id: dict[int, User] = {}
        self._next_id = 1

    async def add(self, user: User) -> None:
        user.id = self._next_id
        self._next_id += 1
        self._by_id[user.id] = user

    async def get_by_id(self, user_id: int) -> User:
        try:
            return self._by_id[user_id]
        except KeyError:
            raise NotFoundError("User not found", user_id=user_id) from None

    async def find_by_id(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)

    async def find_by_public_id(self, public_id: uuid.UUID) -> User | None:
        return next((u for u in self._by_id.values() if u.public_id == public_id), None)

    async def find_by_telegram_id(self, telegram_id: int) -> User | None:
        return None

    async def update(self, user: User) -> None:
        if user.id not in self._by_id:
            raise NotFoundError("User not found", user_id=user.id)
        self._by_id[user.id] = user


class FakeTelegramAccountRepository:
    """Implements
    :class:`~ssa.domain.identity.repositories.TelegramAccountRepository`,
    including the two invariants the real schema enforces structurally: at
    most one account per user (PK ``user_id``) and a globally unique
    ``telegram_id``."""

    def __init__(self) -> None:
        self._by_user_id: dict[int, TelegramAccount] = {}
        self._telegram_ids: set[int] = set()

    async def add(self, account: TelegramAccount) -> None:
        if account.user_id in self._by_user_id:
            raise ConflictError(
                "User already has a linked Telegram account", user_id=account.user_id
            )
        if account.telegram_id in self._telegram_ids:
            raise ConflictError(
                "Telegram account already linked to another user",
                telegram_id=account.telegram_id,
            )
        self._by_user_id[account.user_id] = account
        self._telegram_ids.add(account.telegram_id)

    async def get_by_user_id(self, user_id: int) -> TelegramAccount:
        try:
            return self._by_user_id[user_id]
        except KeyError:
            raise NotFoundError("Telegram account not found", user_id=user_id) from None

    async def find_by_user_id(self, user_id: int) -> TelegramAccount | None:
        return self._by_user_id.get(user_id)

    async def update(self, account: TelegramAccount) -> None:
        if account.user_id not in self._by_user_id:
            raise NotFoundError("Telegram account not found", user_id=account.user_id)
        self._by_user_id[account.user_id] = account


class FakePrivacySettingsRepository:
    """Implements
    :class:`~ssa.domain.identity.repositories.PrivacySettingsRepository`."""

    def __init__(self) -> None:
        self._by_user_id: dict[int, PrivacySettings] = {}

    async def add(self, settings: PrivacySettings) -> None:
        if settings.user_id in self._by_user_id:
            raise ConflictError("Privacy settings already exist", user_id=settings.user_id)
        self._by_user_id[settings.user_id] = settings

    async def get_by_user_id(self, user_id: int) -> PrivacySettings:
        try:
            return self._by_user_id[user_id]
        except KeyError:
            raise NotFoundError("Privacy settings not found", user_id=user_id) from None

    async def find_by_user_id(self, user_id: int) -> PrivacySettings | None:
        return self._by_user_id.get(user_id)

    async def update(self, settings: PrivacySettings) -> None:
        if settings.user_id not in self._by_user_id:
            raise NotFoundError("Privacy settings not found", user_id=settings.user_id)
        self._by_user_id[settings.user_id] = settings


class FakeSubjectRepository:
    """Implements :class:`~ssa.domain.tracking.repositories.SubjectRepository`,
    including the case-insensitive per-user unique name constraint (06 §5) —
    checked against archived subjects too, matching ``uq_subjects_user_name``.
    """

    def __init__(self) -> None:
        self._by_id: dict[int, Subject] = {}
        self._next_id = 1

    async def add(self, subject: Subject) -> None:
        duplicate = any(
            existing.user_id == subject.user_id and existing.name.lower() == subject.name.lower()
            for existing in self._by_id.values()
        )
        if duplicate:
            raise ConflictError(
                "Subject name already exists for this user",
                user_id=subject.user_id,
                name=subject.name,
            )
        subject.id = self._next_id
        self._next_id += 1
        self._by_id[subject.id] = subject

    async def get_by_id(self, subject_id: int) -> Subject:
        try:
            return self._by_id[subject_id]
        except KeyError:
            raise NotFoundError("Subject not found", subject_id=subject_id) from None

    async def find_by_id(self, subject_id: int) -> Subject | None:
        return self._by_id.get(subject_id)

    async def list_for_user(self, user_id: int, *, include_archived: bool = False) -> list[Subject]:
        return [
            subject
            for subject in self._by_id.values()
            if subject.user_id == user_id and (include_archived or not subject.is_archived)
        ]

    async def update(self, subject: Subject) -> None:
        if subject.id not in self._by_id:
            raise NotFoundError("Subject not found", subject_id=subject.id)
        self._by_id[subject.id] = subject
