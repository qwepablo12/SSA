"""Integration tests for the identity repositories (02_Project_Structure.md §9
step 4).

Each ``update`` assertion calls ``session.expire_all()`` before reading the
entity back through the repository — that forces a real ``SELECT`` inside the
still-open transaction, so the assertion checks what was actually written to
the row rather than just the in-memory object the repository already held.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ssa.domain.common.errors import NotFoundError
from ssa.domain.identity.entities import PrivacySettings, TelegramAccount, User
from ssa.domain.identity.enums import UserStatus, Visibility
from ssa.infrastructure.database.repositories import (
    SqlAlchemyPrivacySettingsRepository,
    SqlAlchemyTelegramAccountRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


def _new_user(**overrides: object) -> User:
    now = datetime.now(UTC)
    fields: dict[str, object] = {
        "public_id": uuid.uuid4(),
        "timezone": "UTC",
        "locale": "en",
        "status": UserStatus.ACTIVE,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return User(**fields)  # type: ignore[arg-type]


class TestUserRepository:
    async def test_add_assigns_the_generated_id(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        user = _new_user()
        assert user.id is None

        await repo.add(user)

        assert user.id is not None

    async def test_get_by_id_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(999_999)

    async def test_find_by_id_returns_none_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        assert await repo.find_by_id(999_999) is None

    async def test_find_by_id_round_trips_the_entity(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        user = _new_user(display_name="Ada")
        await repo.add(user)

        found = await repo.find_by_id(user.id)

        assert found is not None
        assert found.id == user.id
        assert found.public_id == user.public_id
        assert found.display_name == "Ada"
        assert found.status is UserStatus.ACTIVE

    async def test_find_by_public_id(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        user = _new_user()
        await repo.add(user)

        found = await repo.find_by_public_id(user.public_id)

        assert found is not None
        assert found.id == user.id

    async def test_find_by_public_id_returns_none_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        assert await repo.find_by_public_id(uuid.uuid4()) is None

    async def test_find_by_telegram_id(self, session: AsyncSession) -> None:
        user_repo = SqlAlchemyUserRepository(session)
        account_repo = SqlAlchemyTelegramAccountRepository(session)
        user = _new_user()
        await user_repo.add(user)
        await account_repo.add(
            TelegramAccount(
                user_id=user.id,
                telegram_id=555,
                chat_id=555,
                linked_at=datetime.now(UTC),
            )
        )

        found = await user_repo.find_by_telegram_id(555)

        assert found is not None
        assert found.id == user.id

    async def test_find_by_telegram_id_returns_none_when_absent(
        self, session: AsyncSession
    ) -> None:
        repo = SqlAlchemyUserRepository(session)
        assert await repo.find_by_telegram_id(404) is None

    async def test_update_persists_changes_made_through_entity_methods(
        self, session: AsyncSession
    ) -> None:
        repo = SqlAlchemyUserRepository(session)
        user = _new_user()
        await repo.add(user)

        user.change_timezone("America/New_York")
        user.complete_onboarding(at=datetime.now(UTC))
        await repo.update(user)
        await session.flush()
        session.expire_all()

        reloaded = await repo.get_by_id(user.id)
        assert reloaded.timezone == "America/New_York"
        assert reloaded.onboarding_completed_at is not None

    async def test_update_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        user = _new_user(id=999_999)
        with pytest.raises(NotFoundError):
            await repo.update(user)


class TestTelegramAccountRepository:
    async def test_add_and_get_by_user_id(self, session: AsyncSession) -> None:
        user = _new_user()
        await SqlAlchemyUserRepository(session).add(user)
        repo = SqlAlchemyTelegramAccountRepository(session)
        account = TelegramAccount(
            user_id=user.id,
            telegram_id=42,
            chat_id=42,
            linked_at=datetime.now(UTC),
            telegram_username="ada",
        )

        await repo.add(account)

        found = await repo.get_by_user_id(user.id)
        assert found.telegram_id == 42
        assert found.telegram_username == "ada"

    async def test_get_by_user_id_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyTelegramAccountRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_user_id(999_999)

    async def test_find_by_user_id_returns_none_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyTelegramAccountRepository(session)
        assert await repo.find_by_user_id(999_999) is None

    async def test_update_persists_activity(self, session: AsyncSession) -> None:
        user = _new_user()
        await SqlAlchemyUserRepository(session).add(user)
        repo = SqlAlchemyTelegramAccountRepository(session)
        account = TelegramAccount(
            user_id=user.id, telegram_id=7, chat_id=7, linked_at=datetime.now(UTC)
        )
        await repo.add(account)

        seen_at = datetime.now(UTC)
        account.record_activity(at=seen_at)
        await repo.update(account)
        await session.flush()
        session.expire_all()

        reloaded = await repo.get_by_user_id(user.id)
        assert reloaded.last_seen_at == seen_at


class TestPrivacySettingsRepository:
    async def test_add_and_get_by_user_id(self, session: AsyncSession) -> None:
        user = _new_user()
        await SqlAlchemyUserRepository(session).add(user)
        repo = SqlAlchemyPrivacySettingsRepository(session)
        settings = PrivacySettings(user_id=user.id, updated_at=datetime.now(UTC))

        await repo.add(settings)

        found = await repo.get_by_user_id(user.id)
        assert found.profile_visibility is Visibility.PRIVATE
        assert found.research_consent is False

    async def test_get_by_user_id_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyPrivacySettingsRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_user_id(999_999)

    async def test_update_persists_research_consent(self, session: AsyncSession) -> None:
        user = _new_user()
        await SqlAlchemyUserRepository(session).add(user)
        repo = SqlAlchemyPrivacySettingsRepository(session)
        settings = PrivacySettings(user_id=user.id, updated_at=datetime.now(UTC))
        await repo.add(settings)

        settings.grant_research_consent(at=datetime.now(UTC))
        await repo.update(settings)
        await session.flush()
        session.expire_all()

        reloaded = await repo.get_by_user_id(user.id)
        assert reloaded.research_consent is True
        assert reloaded.research_consent_at is not None
