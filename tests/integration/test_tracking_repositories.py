"""Integration tests for the tracking repositories (02_Project_Structure.md
§9 step 4).

Each ``update`` assertion calls ``session.expire_all()`` before reading the
entity back through the repository, forcing a real ``SELECT`` inside the
still-open transaction rather than checking the in-memory object the
repository already held.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from ssa.domain.common.errors import NotFoundError
from ssa.domain.tracking.entities import ExerciseLog, MoodLog, SleepLog, StudySession, Subject
from ssa.domain.tracking.enums import SessionStatus
from ssa.infrastructure.database import models
from ssa.infrastructure.database.repositories import (
    SqlAlchemyExerciseLogRepository,
    SqlAlchemyMoodLogRepository,
    SqlAlchemySleepLogRepository,
    SqlAlchemyStudySessionRepository,
    SqlAlchemySubjectRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def user_id(session: AsyncSession) -> int:
    """A bare persisted user to satisfy the FK — not itself under test here,
    so it goes straight through the ORM model, matching
    ``test_schema_constraints.py``."""
    user = models.User()
    session.add(user)
    await session.flush()
    return user.id


class TestSubjectRepository:
    async def test_add_assigns_the_generated_id(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemySubjectRepository(session)
        now = datetime.now(UTC)
        subject = Subject(user_id=user_id, name="Maths", created_at=now, updated_at=now)

        await repo.add(subject)

        assert subject.id is not None

    async def test_get_by_id_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemySubjectRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(999_999)

    async def test_find_by_id_returns_none_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemySubjectRepository(session)
        assert await repo.find_by_id(999_999) is None

    async def test_list_for_user_excludes_archived_by_default(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemySubjectRepository(session)
        now = datetime.now(UTC)
        active = Subject(user_id=user_id, name="Physics", created_at=now, updated_at=now)
        archived = Subject(
            user_id=user_id, name="History", created_at=now, updated_at=now, is_archived=True
        )
        await repo.add(active)
        await repo.add(archived)

        visible = await repo.list_for_user(user_id)
        assert [s.name for s in visible] == ["Physics"]

        everything = await repo.list_for_user(user_id, include_archived=True)
        assert {s.name for s in everything} == {"Physics", "History"}

    async def test_update_persists_rename_and_archive(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemySubjectRepository(session)
        now = datetime.now(UTC)
        subject = Subject(user_id=user_id, name="Chemistry", created_at=now, updated_at=now)
        await repo.add(subject)

        subject.rename("Organic Chemistry")
        subject.archive()
        await repo.update(subject)
        await session.flush()
        session.expire_all()

        reloaded = await repo.get_by_id(subject.id)
        assert reloaded.name == "Organic Chemistry"
        assert reloaded.is_archived is True


class TestStudySessionRepository:
    async def test_add_assigns_the_generated_id(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        started = datetime.now(UTC)
        now_session = StudySession(
            user_id=user_id,
            started_at=started,
            local_date=started.date(),
            created_at=started,
            updated_at=started,
        )

        await repo.add(now_session)

        assert now_session.id is not None

    async def test_get_by_id_raises_not_found_when_absent(self, session: AsyncSession) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(999_999)

    async def test_find_active_for_user(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        started = datetime.now(UTC)
        active = StudySession(
            user_id=user_id,
            started_at=started,
            local_date=started.date(),
            created_at=started,
            updated_at=started,
        )
        await repo.add(active)

        found = await repo.find_active_for_user(user_id)

        assert found is not None
        assert found.id == active.id

    async def test_find_active_for_user_returns_none_once_completed(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        started = datetime.now(UTC)
        active = StudySession(
            user_id=user_id,
            started_at=started,
            local_date=started.date(),
            created_at=started,
            updated_at=started,
        )
        await repo.add(active)

        active.complete(ended_at=started + timedelta(minutes=30), focus_score=4)
        await repo.update(active)
        await session.flush()
        session.expire_all()

        assert await repo.find_active_for_user(user_id) is None

    async def test_update_persists_completion(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        started = datetime.now(UTC)
        entity = StudySession(
            user_id=user_id,
            started_at=started,
            local_date=started.date(),
            created_at=started,
            updated_at=started,
        )
        await repo.add(entity)

        ended = started + timedelta(minutes=45)
        entity.complete(ended_at=ended, focus_score=5)
        await repo.update(entity)
        await session.flush()
        session.expire_all()

        reloaded = await repo.get_by_id(entity.id)
        assert reloaded.focus_score == 5
        assert reloaded.ended_at == ended

    async def test_list_for_user_filters_by_date_range(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemyStudySessionRepository(session)
        for day in (1, 15):
            started = datetime(2026, 1, day, 10, 0, tzinfo=UTC)
            session_entity = StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started + timedelta(minutes=10),
                local_date=started.date(),
                status=SessionStatus.COMPLETED,
                created_at=started,
                updated_at=started,
            )
            await repo.add(session_entity)

        recent_only = await repo.list_for_user(
            user_id, since=date(2026, 1, 10), until=date(2026, 1, 31)
        )
        assert [s.local_date for s in recent_only] == [date(2026, 1, 15)]


class TestSleepLogRepository:
    async def test_add_and_find_for_user_on_date(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemySleepLogRepository(session)
        now = datetime.now(UTC)
        log = SleepLog(
            user_id=user_id,
            local_date=date(2026, 1, 1),
            duration_minutes=420,
            created_at=now,
            updated_at=now,
        )

        await repo.add(log)

        found = await repo.find_for_user_on_date(user_id, date(2026, 1, 1))
        assert found is not None
        assert found.duration_minutes == 420

    async def test_find_for_user_on_date_returns_none_for_a_different_night(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemySleepLogRepository(session)
        now = datetime.now(UTC)
        await repo.add(
            SleepLog(
                user_id=user_id,
                local_date=date(2026, 1, 1),
                duration_minutes=420,
                created_at=now,
                updated_at=now,
            )
        )

        assert await repo.find_for_user_on_date(user_id, date(2026, 1, 2)) is None


class TestMoodLogRepository:
    async def test_multiple_entries_per_day_are_listed(
        self, session: AsyncSession, user_id: int
    ) -> None:
        repo = SqlAlchemyMoodLogRepository(session)
        morning = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
        evening = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
        await repo.add(
            MoodLog(
                user_id=user_id,
                recorded_at=morning,
                local_date=date(2026, 1, 1),
                mood=3,
                created_at=morning,
            )
        )
        await repo.add(
            MoodLog(
                user_id=user_id,
                recorded_at=evening,
                local_date=date(2026, 1, 1),
                mood=4,
                created_at=evening,
            )
        )

        entries = await repo.list_for_user_on_date(user_id, date(2026, 1, 1))

        assert [e.mood for e in entries] == [4, 3]


class TestExerciseLogRepository:
    async def test_add_and_list_for_user_on_date(self, session: AsyncSession, user_id: int) -> None:
        repo = SqlAlchemyExerciseLogRepository(session)
        occurred = datetime(2026, 1, 1, 7, 0, tzinfo=UTC)
        log = ExerciseLog(
            user_id=user_id,
            occurred_at=occurred,
            local_date=date(2026, 1, 1),
            duration_minutes=30,
            created_at=occurred,
        )

        await repo.add(log)

        entries = await repo.list_for_user_on_date(user_id, date(2026, 1, 1))
        assert len(entries) == 1
        assert entries[0].duration_minutes == 30
