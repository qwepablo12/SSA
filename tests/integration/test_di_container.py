"""Integration test for the Dishka container wiring (02_Project_Structure.md
§9 step 6) — resolves a full ``REQUEST`` scope through both providers and
executes real use cases against Postgres.

The container is handed ``session_factory`` (bound to this test's rolled-back
transaction, ``tests/conftest.py``) rather than building its own engine, so a
committed use case leaves no trace once the test ends — the same isolation
guarantee every other integration test relies on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from dishka import make_async_container
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ssa.application.common.di import ApplicationProvider
from ssa.application.identity.dto import OnboardUserRequest, RegisterUserRequest
from ssa.application.identity.use_cases.onboard_user import OnboardUser
from ssa.application.identity.use_cases.register_user import RegisterUser
from ssa.application.tracking.dto import CreateSubjectRequest
from ssa.application.tracking.use_cases.create_subject import CreateSubject
from ssa.domain.common.errors import NotFoundError
from ssa.infrastructure.di import InfrastructureProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from dishka import AsyncContainer

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def container(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncContainer]:
    built = make_async_container(
        InfrastructureProvider(),
        ApplicationProvider(),
        context={async_sessionmaker[AsyncSession]: session_factory},
    )
    try:
        yield built
    finally:
        await built.close()


async def test_register_user_resolves_and_commits_through_the_container(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        use_case = await request_scope.get(RegisterUser)
        result = await use_case.execute(RegisterUserRequest(timezone="Europe/London"))

    assert result.user_id is not None
    assert result.public_id is not None


async def test_create_subject_resolves_through_the_container(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        create_subject = await request_scope.get(CreateSubject)
        result = await create_subject.execute(
            CreateSubjectRequest(user_id=user.user_id, name="Maths")
        )

    assert result.subject_id is not None
    assert result.name == "Maths"


async def test_errors_propagate_through_a_container_resolved_use_case(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        create_subject = await request_scope.get(CreateSubject)
        with pytest.raises(NotFoundError):
            await create_subject.execute(CreateSubjectRequest(user_id=999_999, name="Maths"))


async def test_onboard_user_registers_a_new_telegram_user(
    container: AsyncContainer,
) -> None:
    """Exercises the nested-use-case path: ``OnboardUser`` calls the
    undecorated cores of ``RegisterUser`` and ``LinkTelegramAccount`` so all
    three writes land in one commit, not three."""
    async with container() as request_scope:
        onboard_user = await request_scope.get(OnboardUser)
        result = await onboard_user.execute(
            OnboardUserRequest(telegram_id=1_001, chat_id=2_001, display_name="Ada")
        )

    assert result.is_new_user is True
    assert result.user_id is not None


async def test_onboard_user_recognises_a_returning_telegram_user(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        onboard_user = await request_scope.get(OnboardUser)
        first = await onboard_user.execute(
            OnboardUserRequest(telegram_id=1_002, chat_id=2_002, display_name="Grace")
        )

    async with container() as request_scope:
        onboard_user = await request_scope.get(OnboardUser)
        second = await onboard_user.execute(
            OnboardUserRequest(telegram_id=1_002, chat_id=2_002, display_name="Grace")
        )

    assert second.is_new_user is False
    assert second.user_id == first.user_id
    assert second.public_id == first.public_id
