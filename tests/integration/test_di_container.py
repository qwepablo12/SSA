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
from ssa.application.tracking.dto import (
    CompleteStudySessionRequest,
    CreateSubjectRequest,
    GetStudyHistoryRequest,
    StartStudySessionRequest,
)
from ssa.application.tracking.use_cases.complete_study_session import CompleteStudySession
from ssa.application.tracking.use_cases.create_subject import CreateSubject
from ssa.application.tracking.use_cases.get_study_history import GetStudyHistory
from ssa.application.tracking.use_cases.start_study_session import StartStudySession
from ssa.domain.common.errors import ConflictError, NotFoundError
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


async def test_start_and_complete_a_study_session(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        started = await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))

    assert started.session_id is not None

    async with container() as request_scope:
        complete_study_session = await request_scope.get(CompleteStudySession)
        completed = await complete_study_session.execute(
            CompleteStudySessionRequest(user_id=user.user_id, focus_score=4)
        )

    assert completed.session_id == started.session_id
    assert completed.focus_score == 4
    assert completed.duration_minutes >= 0


async def test_start_study_session_rejects_a_second_concurrent_session(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        with pytest.raises(ConflictError):
            await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))


async def test_complete_study_session_without_an_active_session_raises_not_found(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        complete_study_session = await request_scope.get(CompleteStudySession)
        with pytest.raises(NotFoundError):
            await complete_study_session.execute(CompleteStudySessionRequest(user_id=user.user_id))


async def test_start_study_session_with_a_valid_subject_attaches_it(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        create_subject = await request_scope.get(CreateSubject)
        subject = await create_subject.execute(
            CreateSubjectRequest(user_id=user.user_id, name="Math")
        )

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        # Matching is case-insensitive (mirrors `uq_subjects_user_name`).
        started = await start_study_session.execute(
            StartStudySessionRequest(user_id=user.user_id, subject_name="math")
        )

    assert started.subject_id == subject.subject_id


async def test_start_study_session_with_an_unknown_subject_raises_not_found(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        with pytest.raises(NotFoundError):
            await start_study_session.execute(
                StartStudySessionRequest(user_id=user.user_id, subject_name="Physics")
            )


async def test_start_study_session_cannot_use_another_users_subject(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        owner = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        other = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        create_subject = await request_scope.get(CreateSubject)
        await create_subject.execute(CreateSubjectRequest(user_id=owner.user_id, name="Math"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        with pytest.raises(NotFoundError):
            await start_study_session.execute(
                StartStudySessionRequest(user_id=other.user_id, subject_name="Math")
            )


async def test_get_study_history_is_empty_for_a_user_with_no_sessions(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        get_study_history = await request_scope.get(GetStudyHistory)
        result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user.user_id))

    assert result.entries == []


async def test_get_study_history_orders_completed_sessions_newest_first(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        complete_study_session = await request_scope.get(CompleteStudySession)
        first = await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))
        first_completed = await complete_study_session.execute(
            CompleteStudySessionRequest(user_id=user.user_id)
        )

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        complete_study_session = await request_scope.get(CompleteStudySession)
        second = await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))
        second_completed = await complete_study_session.execute(
            CompleteStudySessionRequest(user_id=user.user_id)
        )

    async with container() as request_scope:
        get_study_history = await request_scope.get(GetStudyHistory)
        result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user.user_id))

    assert [entry.session_id for entry in result.entries] == [second.session_id, first.session_id]
    assert result.entries[0].ended_at == second_completed.ended_at
    assert result.entries[1].ended_at == first_completed.ended_at


async def test_get_study_history_entry_without_a_subject_has_no_subject_name(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        complete_study_session = await request_scope.get(CompleteStudySession)
        await start_study_session.execute(StartStudySessionRequest(user_id=user.user_id))
        await complete_study_session.execute(CompleteStudySessionRequest(user_id=user.user_id))

    async with container() as request_scope:
        get_study_history = await request_scope.get(GetStudyHistory)
        result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user.user_id))

    assert len(result.entries) == 1
    assert result.entries[0].subject_id is None
    assert result.entries[0].subject_name is None


async def test_get_study_history_entry_with_a_subject_includes_its_name(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        create_subject = await request_scope.get(CreateSubject)
        subject = await create_subject.execute(
            CreateSubjectRequest(user_id=user.user_id, name="Math")
        )

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        complete_study_session = await request_scope.get(CompleteStudySession)
        await start_study_session.execute(
            StartStudySessionRequest(user_id=user.user_id, subject_name="Math")
        )
        await complete_study_session.execute(CompleteStudySessionRequest(user_id=user.user_id))

    async with container() as request_scope:
        get_study_history = await request_scope.get(GetStudyHistory)
        result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user.user_id))

    assert len(result.entries) == 1
    assert result.entries[0].subject_id == subject.subject_id
    assert result.entries[0].subject_name == "Math"


async def test_get_study_history_only_returns_the_requesting_users_sessions(
    container: AsyncContainer,
) -> None:
    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user_a = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        register_user = await request_scope.get(RegisterUser)
        user_b = await register_user.execute(RegisterUserRequest(timezone="UTC"))

    async with container() as request_scope:
        start_study_session = await request_scope.get(StartStudySession)
        complete_study_session = await request_scope.get(CompleteStudySession)
        await start_study_session.execute(StartStudySessionRequest(user_id=user_b.user_id))
        await complete_study_session.execute(CompleteStudySessionRequest(user_id=user_b.user_id))

    async with container() as request_scope:
        get_study_history = await request_scope.get(GetStudyHistory)
        result = await get_study_history.execute(GetStudyHistoryRequest(user_id=user_a.user_id))

    assert result.entries == []
