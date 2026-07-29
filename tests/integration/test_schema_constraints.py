"""Constraint and relationship tests for migration 001 (identity + tracking).

These exercise the ORM models directly against a real Postgres, per
06_Database_Schema.md §19 Step 8: assert that each constraint actually rejects
what it claims to — "an unenforced constraint is a comment." No repositories
exist yet, so these go through the ``session`` fixture rather than a unit of
work: the constraint's behaviour is what is under test here, not its
translation into a domain error (a later step's job).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ssa.infrastructure.database.models import (
    ExerciseLog,
    MoodLog,
    PrivacySettings,
    SleepLog,
    StudySession,
    Subject,
    TelegramAccount,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def user_id(session: AsyncSession) -> int:
    user = User()
    session.add(user)
    await session.flush()
    return user.id


class TestUsers:
    async def test_status_must_be_a_known_value(self, session: AsyncSession) -> None:
        session.add(User(status="on_vacation"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_timezone_cannot_be_blank(self, session: AsyncSession) -> None:
        session.add(User(timezone="   "))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_display_name_cannot_be_empty_string(self, session: AsyncSession) -> None:
        session.add(User(display_name=""))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_public_id_is_unique(self, session: AsyncSession) -> None:
        shared = uuid.uuid4()
        session.add(User(public_id=shared))
        await session.flush()
        session.add(User(public_id=shared))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestTelegramAccounts:
    async def test_telegram_id_must_be_positive(self, session: AsyncSession, user_id: int) -> None:
        session.add(TelegramAccount(user_id=user_id, telegram_id=-1, chat_id=1))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_username_length_limit(self, session: AsyncSession, user_id: int) -> None:
        session.add(
            TelegramAccount(user_id=user_id, telegram_id=1, chat_id=1, telegram_username="x" * 33)
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_telegram_id_is_unique(self, session: AsyncSession, user_id: int) -> None:
        other = User()
        session.add(other)
        await session.flush()
        session.add(TelegramAccount(user_id=user_id, telegram_id=42, chat_id=42))
        await session.flush()
        session.add(TelegramAccount(user_id=other.id, telegram_id=42, chat_id=99))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_only_one_account_per_user(self, session: AsyncSession, user_id: int) -> None:
        """``user_id`` is the primary key — the 1:1 is structural, not just checked."""
        session.add(TelegramAccount(user_id=user_id, telegram_id=1, chat_id=1))
        await session.flush()
        session.add(TelegramAccount(user_id=user_id, telegram_id=2, chat_id=2))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_cascades_on_user_delete(self, session: AsyncSession) -> None:
        user = User()
        session.add(user)
        await session.flush()
        session.add(TelegramAccount(user_id=user.id, telegram_id=7, chat_id=7))
        await session.flush()

        await session.delete(user)
        await session.flush()

        remaining = await session.scalar(
            select(func.count())
            .select_from(TelegramAccount)
            .where(TelegramAccount.user_id == user.id)
        )
        assert remaining == 0


class TestPrivacySettings:
    async def test_visibility_must_be_a_known_value(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(PrivacySettings(user_id=user_id, profile_visibility="public"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_research_consent_requires_a_timestamp(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(
            PrivacySettings(user_id=user_id, research_consent=True, research_consent_at=None)
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_research_consent_with_timestamp_is_allowed(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(
            PrivacySettings(
                user_id=user_id, research_consent=True, research_consent_at=datetime.now(UTC)
            )
        )
        await session.flush()


class TestSubjects:
    async def test_name_cannot_be_blank(self, session: AsyncSession, user_id: int) -> None:
        session.add(Subject(user_id=user_id, name="   "))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_colour_must_be_hex(self, session: AsyncSession, user_id: int) -> None:
        session.add(Subject(user_id=user_id, name="Maths", colour="blue"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_name_is_unique_per_user_case_insensitively(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(Subject(user_id=user_id, name="Maths"))
        await session.flush()
        session.add(Subject(user_id=user_id, name="maths"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_same_name_allowed_for_different_users(
        self, session: AsyncSession, user_id: int
    ) -> None:
        other = User()
        session.add(other)
        await session.flush()

        session.add(Subject(user_id=user_id, name="Maths"))
        session.add(Subject(user_id=other.id, name="Maths"))
        await session.flush()


class TestStudySessions:
    async def test_status_must_be_a_known_value(self, session: AsyncSession, user_id: int) -> None:
        started = datetime.now(UTC)
        session.add(
            StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started + timedelta(minutes=1),
                local_date=started.date(),
                status="paused",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_ended_at_must_be_after_started_at(
        self, session: AsyncSession, user_id: int
    ) -> None:
        started = datetime.now(UTC)
        session.add(
            StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started - timedelta(minutes=1),
                local_date=started.date(),
                status="completed",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_in_progress_session_cannot_have_an_end_time(
        self, session: AsyncSession, user_id: int
    ) -> None:
        started = datetime.now(UTC)
        session.add(
            StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started + timedelta(minutes=1),
                local_date=started.date(),
                status="in_progress",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_session_cannot_exceed_twelve_hours(
        self, session: AsyncSession, user_id: int
    ) -> None:
        started = datetime.now(UTC)
        session.add(
            StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started + timedelta(hours=20),
                local_date=started.date(),
                status="completed",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_focus_score_out_of_range(self, session: AsyncSession, user_id: int) -> None:
        started = datetime.now(UTC)
        session.add(
            StudySession(
                user_id=user_id,
                started_at=started,
                ended_at=started + timedelta(minutes=30),
                local_date=started.date(),
                status="completed",
                focus_score=9,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_only_one_in_progress_session_per_user(
        self, session: AsyncSession, user_id: int
    ) -> None:
        started = datetime.now(UTC)
        session.add(StudySession(user_id=user_id, started_at=started, local_date=started.date()))
        await session.flush()

        session.add(
            StudySession(
                user_id=user_id,
                started_at=started + timedelta(minutes=5),
                local_date=started.date(),
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_duration_seconds_is_computed_from_timestamps(
        self, session: AsyncSession, user_id: int
    ) -> None:
        started = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        ended = started + timedelta(minutes=30)
        row = StudySession(
            user_id=user_id,
            started_at=started,
            ended_at=ended,
            local_date=started.date(),
            status="completed",
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        assert row.duration_seconds == 1800

    async def test_deleting_a_subject_sets_subject_id_null(
        self, session: AsyncSession, user_id: int
    ) -> None:
        subject = Subject(user_id=user_id, name="Physics")
        session.add(subject)
        await session.flush()

        started = datetime.now(UTC)
        row = StudySession(
            user_id=user_id,
            subject_id=subject.id,
            started_at=started,
            ended_at=started + timedelta(minutes=10),
            local_date=started.date(),
            status="completed",
        )
        session.add(row)
        await session.flush()

        await session.delete(subject)
        await session.flush()
        await session.refresh(row)
        assert row.subject_id is None

    async def test_cascades_on_user_delete(self, session: AsyncSession) -> None:
        user = User()
        session.add(user)
        await session.flush()

        started = datetime.now(UTC)
        session.add(StudySession(user_id=user.id, started_at=started, local_date=started.date()))
        await session.flush()

        await session.delete(user)
        await session.flush()

        remaining = await session.scalar(
            select(func.count()).select_from(StudySession).where(StudySession.user_id == user.id)
        )
        assert remaining == 0


class TestSleepLogs:
    async def test_duration_must_be_in_range(self, session: AsyncSession, user_id: int) -> None:
        session.add(SleepLog(user_id=user_id, local_date=date(2026, 1, 1), duration_minutes=1500))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_quality_out_of_range(self, session: AsyncSession, user_id: int) -> None:
        session.add(
            SleepLog(user_id=user_id, local_date=date(2026, 1, 1), duration_minutes=420, quality=6)
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_wake_must_be_after_bedtime(self, session: AsyncSession, user_id: int) -> None:
        bed = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
        session.add(
            SleepLog(
                user_id=user_id,
                local_date=date(2026, 1, 2),
                duration_minutes=420,
                bedtime_at=bed,
                wake_at=bed - timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_one_sleep_log_per_user_per_night(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(SleepLog(user_id=user_id, local_date=date(2026, 1, 1), duration_minutes=420))
        await session.flush()

        session.add(SleepLog(user_id=user_id, local_date=date(2026, 1, 1), duration_minutes=300))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestMoodLogs:
    async def test_mood_out_of_range(self, session: AsyncSession, user_id: int) -> None:
        session.add(MoodLog(user_id=user_id, local_date=date(2026, 1, 1), mood=0))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_note_length_limit(self, session: AsyncSession, user_id: int) -> None:
        session.add(MoodLog(user_id=user_id, local_date=date(2026, 1, 1), mood=3, note="x" * 1001))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_multiple_entries_per_day_are_allowed(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(MoodLog(user_id=user_id, local_date=date(2026, 1, 1), mood=3))
        session.add(MoodLog(user_id=user_id, local_date=date(2026, 1, 1), mood=4))
        await session.flush()


class TestExerciseLogs:
    async def test_duration_must_be_in_range(self, session: AsyncSession, user_id: int) -> None:
        session.add(
            ExerciseLog(
                user_id=user_id,
                occurred_at=datetime.now(UTC),
                local_date=date(2026, 1, 1),
                duration_minutes=0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_activity_type_must_be_a_known_value(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(
            ExerciseLog(
                user_id=user_id,
                occurred_at=datetime.now(UTC),
                local_date=date(2026, 1, 1),
                duration_minutes=30,
                activity_type="yoga",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_intensity_must_be_a_known_value(
        self, session: AsyncSession, user_id: int
    ) -> None:
        session.add(
            ExerciseLog(
                user_id=user_id,
                occurred_at=datetime.now(UTC),
                local_date=date(2026, 1, 1),
                duration_minutes=30,
                intensity="extreme",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
