"""Unit tests for the identity application use cases. No database, no event
loop beyond asyncio itself — every dependency is a hand-rolled fake
implementing the domain protocols (``tests/unit/fakes.py``).
"""

from __future__ import annotations

import uuid

import pytest

from ssa.application.identity.dto import (
    LinkTelegramAccountRequest,
    RegisterUserRequest,
    UpdatePrivacySettingsRequest,
)
from ssa.application.identity.use_cases.link_telegram_account import LinkTelegramAccount
from ssa.application.identity.use_cases.register_user import RegisterUser
from ssa.application.identity.use_cases.update_privacy_settings import UpdatePrivacySettings
from ssa.domain.common.errors import ConflictError, NotFoundError, ValidationError
from ssa.domain.identity.entities import PrivacySettings, User
from ssa.domain.identity.enums import UserStatus, Visibility
from tests.unit.fakes import (
    FakeClock,
    FakePrivacySettingsRepository,
    FakeTelegramAccountRepository,
    FakeUnitOfWork,
    FakeUserRepository,
)


async def _persisted_user(users: FakeUserRepository, clock: FakeClock) -> int:
    user = User(
        public_id=uuid.uuid4(),
        timezone="UTC",
        locale="en",
        status=UserStatus.ACTIVE,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    await users.add(user)
    assert user.id is not None
    return user.id


class TestRegisterUser:
    async def test_creates_user_and_default_privacy_settings(self) -> None:
        privacy_settings = FakePrivacySettingsRepository()
        uow = FakeUnitOfWork()
        use_case = RegisterUser(
            users=FakeUserRepository(),
            privacy_settings=privacy_settings,
            clock=FakeClock(),
            uow=uow,
        )

        result = await use_case.execute(RegisterUserRequest(timezone="Europe/London"))

        assert result.status is UserStatus.ACTIVE
        assert result.public_id is not None
        settings = await privacy_settings.get_by_user_id(result.user_id)
        assert settings.profile_visibility is Visibility.PRIVATE
        assert settings.leaderboard_opt_in is False
        assert settings.research_consent is False
        assert uow.committed is True

    async def test_rejects_an_unknown_timezone(self) -> None:
        uow = FakeUnitOfWork()
        use_case = RegisterUser(
            users=FakeUserRepository(),
            privacy_settings=FakePrivacySettingsRepository(),
            clock=FakeClock(),
            uow=uow,
        )

        with pytest.raises(ValidationError):
            await use_case.execute(RegisterUserRequest(timezone="Not/AZone"))

        assert uow.committed is False


class TestLinkTelegramAccount:
    async def test_links_a_telegram_account_to_an_existing_user(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        user_id = await _persisted_user(users, clock)
        uow = FakeUnitOfWork()
        use_case = LinkTelegramAccount(
            users=users,
            telegram_accounts=FakeTelegramAccountRepository(),
            clock=clock,
            uow=uow,
        )

        result = await use_case.execute(
            LinkTelegramAccountRequest(user_id=user_id, telegram_id=555, chat_id=555)
        )

        assert result.user_id == user_id
        assert result.telegram_id == 555
        assert uow.committed is True

    async def test_raises_not_found_for_an_unknown_user(self) -> None:
        use_case = LinkTelegramAccount(
            users=FakeUserRepository(),
            telegram_accounts=FakeTelegramAccountRepository(),
            clock=FakeClock(),
            uow=FakeUnitOfWork(),
        )

        with pytest.raises(NotFoundError):
            await use_case.execute(
                LinkTelegramAccountRequest(user_id=999, telegram_id=1, chat_id=1)
            )

    async def test_raises_conflict_when_the_user_already_has_a_linked_account(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        user_id = await _persisted_user(users, clock)
        use_case = LinkTelegramAccount(
            users=users,
            telegram_accounts=FakeTelegramAccountRepository(),
            clock=clock,
            uow=FakeUnitOfWork(),
        )
        await use_case.execute(
            LinkTelegramAccountRequest(user_id=user_id, telegram_id=1, chat_id=1)
        )

        with pytest.raises(ConflictError):
            await use_case.execute(
                LinkTelegramAccountRequest(user_id=user_id, telegram_id=2, chat_id=2)
            )

    async def test_raises_conflict_when_the_telegram_id_is_linked_elsewhere(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        first_user_id = await _persisted_user(users, clock)
        second_user_id = await _persisted_user(users, clock)
        telegram_accounts = FakeTelegramAccountRepository()
        use_case = LinkTelegramAccount(
            users=users, telegram_accounts=telegram_accounts, clock=clock, uow=FakeUnitOfWork()
        )
        await use_case.execute(
            LinkTelegramAccountRequest(user_id=first_user_id, telegram_id=42, chat_id=42)
        )

        with pytest.raises(ConflictError):
            await use_case.execute(
                LinkTelegramAccountRequest(user_id=second_user_id, telegram_id=42, chat_id=42)
            )


class TestUpdatePrivacySettings:
    def _repository_with_settings(
        self, clock: FakeClock, user_id: int = 1
    ) -> FakePrivacySettingsRepository:
        repo = FakePrivacySettingsRepository()
        repo._by_user_id[user_id] = PrivacySettings(user_id=user_id, updated_at=clock.now())
        return repo

    async def test_updates_only_the_fields_provided(self) -> None:
        clock = FakeClock()
        repo = self._repository_with_settings(clock)
        use_case = UpdatePrivacySettings(privacy_settings=repo, clock=clock, uow=FakeUnitOfWork())

        result = await use_case.execute(
            UpdatePrivacySettingsRequest(user_id=1, leaderboard_opt_in=True)
        )

        assert result.leaderboard_opt_in is True
        assert result.profile_visibility is Visibility.PRIVATE
        assert result.research_consent is False

    async def test_granting_research_consent_records_the_timestamp(self) -> None:
        clock = FakeClock()
        repo = self._repository_with_settings(clock)
        use_case = UpdatePrivacySettings(privacy_settings=repo, clock=clock, uow=FakeUnitOfWork())

        result = await use_case.execute(
            UpdatePrivacySettingsRequest(user_id=1, research_consent=True)
        )

        assert result.research_consent is True
        assert result.research_consent_at == clock.now()

    async def test_revoking_research_consent_clears_the_timestamp(self) -> None:
        clock = FakeClock()
        repo = self._repository_with_settings(clock)
        use_case = UpdatePrivacySettings(privacy_settings=repo, clock=clock, uow=FakeUnitOfWork())
        await use_case.execute(UpdatePrivacySettingsRequest(user_id=1, research_consent=True))

        result = await use_case.execute(
            UpdatePrivacySettingsRequest(user_id=1, research_consent=False)
        )

        assert result.research_consent is False
        assert result.research_consent_at is None

    async def test_raises_not_found_when_settings_are_missing(self) -> None:
        use_case = UpdatePrivacySettings(
            privacy_settings=FakePrivacySettingsRepository(),
            clock=FakeClock(),
            uow=FakeUnitOfWork(),
        )

        with pytest.raises(NotFoundError):
            await use_case.execute(UpdatePrivacySettingsRequest(user_id=404))
