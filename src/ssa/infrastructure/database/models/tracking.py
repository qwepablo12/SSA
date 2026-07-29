"""ORM models for the tracking module: ``subjects``, ``study_sessions``,
``sleep_logs``, ``mood_logs``, ``exercise_logs`` (06_Database_Schema.md Part
II).

These are persistence models, not domain entities (ADR-004) — see
``ssa.domain.tracking.entities`` for the rich, framework-free counterparts.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from ssa.infrastructure.database.base import Base
from ssa.infrastructure.database.types import (
    BigIntPK,
    CreatedAt,
    DeletedAt,
    SmallCount,
    SmallInt,
    UpdatedAt,
)

__all__ = ["ExerciseLog", "MoodLog", "SleepLog", "StudySession", "Subject"]


class Subject(Base):
    """User-defined study subject — per-user, not a shared catalogue (06 §5)."""

    __tablename__ = "subjects"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]
    colour: Mapped[str | None]
    is_archived: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("colour IS NULL OR colour ~ '^#[0-9A-Fa-f]{6}$'", name="colour_format"),
        # Functional + case-insensitive: "Maths" and "maths" would otherwise
        # silently split one subject's statistics in two. Archived subjects
        # are included on purpose — reusing a freed name would merge two
        # conceptually distinct subjects in historical charts (06 §5).
        Index(
            "uq_subjects_user_name",
            "user_id",
            text("lower(name)"),
            unique=True,
        ),
        # Partial: the subject picker, rendered on nearly every session start,
        # only ever wants the non-archived set.
        Index(
            "ix_subjects_user_active",
            "user_id",
            postgresql_where=text("NOT is_archived"),
        ),
    )


class StudySession(Base):
    """The primary behavioural record and highest-volume table (06 §6)."""

    __tablename__ = "study_sessions"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(server_default=text("'in_progress'"))
    started_at: Mapped[dt.datetime]
    ended_at: Mapped[dt.datetime | None]
    local_date: Mapped[dt.date]
    # Stored, not computed on read: the value can never disagree with the
    # timestamps it derives from, and the nightly rollup scans millions of
    # rows by date without recomputing this per row (06 §6).
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN ended_at IS NULL THEN NULL "
            "ELSE EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER END",
            persisted=True,
        ),
    )
    planned_minutes: Mapped[SmallInt | None]
    focus_score: Mapped[SmallInt | None]
    session_type: Mapped[str] = mapped_column(server_default=text("'focus'"))
    interruption_count: Mapped[SmallCount]
    notes: Mapped[str | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned', 'discarded')",
            name="status",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="end_after_start"),
        CheckConstraint(
            "(status = 'in_progress') = (ended_at IS NULL)", name="status_end_consistency"
        ),
        # A corruption backstop, not the product rule (8h — domain/tracking/
        # rules.py). 12h catches a forgotten timer without encoding policy
        # that would need a migration to adjust (06 §6).
        CheckConstraint(
            "ended_at IS NULL OR ended_at <= started_at + INTERVAL '12 hours'",
            name="max_duration",
        ),
        CheckConstraint("focus_score IS NULL OR focus_score BETWEEN 1 AND 5", name="focus_range"),
        CheckConstraint(
            "session_type IN ('focus', 'review', 'practice', 'reading', 'other')",
            name="session_type",
        ),
        CheckConstraint("interruption_count >= 0", name="interruptions_non_negative"),
        CheckConstraint(
            "planned_minutes IS NULL OR planned_minutes > 0", name="planned_minutes_positive"
        ),
        # User history — the dominant read pattern.
        Index(
            "ix_study_sessions_user_started",
            "user_id",
            text("started_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # The nightly rollup, which scans one date across all users.
        Index(
            "ix_study_sessions_rollup",
            "local_date",
            "user_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Per-subject breakdowns.
        Index(
            "ix_study_sessions_user_subject",
            "user_id",
            "subject_id",
            "local_date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # At most one running session per user, enforced structurally — the
        # single most likely concurrency bug in the whole bot (double-tapping
        # "start") becomes impossible rather than unlikely (06 §6).
        Index(
            "uq_study_sessions_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
    )


class SleepLog(Base):
    """Daily sleep record, attributed to the wake date (06 §7, Q5)."""

    __tablename__ = "sleep_logs"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    local_date: Mapped[dt.date]
    duration_minutes: Mapped[SmallInt]
    bedtime_at: Mapped[dt.datetime | None]
    wake_at: Mapped[dt.datetime | None]
    quality: Mapped[SmallInt | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        CheckConstraint("duration_minutes BETWEEN 0 AND 1440", name="duration_range"),
        CheckConstraint("quality IS NULL OR quality BETWEEN 1 AND 5", name="quality_range"),
        CheckConstraint(
            "bedtime_at IS NULL OR wake_at IS NULL OR wake_at > bedtime_at",
            name="wake_after_bedtime",
        ),
        # One sleep record per night; re-logging updates rather than appends.
        # Composite, so the naming convention (keyed off the first column
        # only) can't produce this name — it is given explicitly.
        Index("uq_sleep_logs_user_date", "user_id", "local_date", unique=True),
        Index("ix_sleep_logs_local_date", "local_date"),
    )


class MoodLog(Base):
    """Point-in-time affect record; multiple entries per day are normal (06 §8)."""

    __tablename__ = "mood_logs"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    recorded_at: Mapped[CreatedAt]
    local_date: Mapped[dt.date]
    mood: Mapped[SmallInt]
    energy: Mapped[SmallInt | None]
    stress: Mapped[SmallInt | None]
    note: Mapped[str | None]
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        CheckConstraint("mood BETWEEN 1 AND 5", name="mood_range"),
        CheckConstraint("energy IS NULL OR energy BETWEEN 1 AND 5", name="energy_range"),
        CheckConstraint("stress IS NULL OR stress BETWEEN 1 AND 5", name="stress_range"),
        CheckConstraint("note IS NULL OR length(note) <= 1000", name="note_length"),
        Index("ix_mood_logs_user_recorded", "user_id", text("recorded_at DESC")),
        Index("ix_mood_logs_local_date", "local_date"),
    )


class ExerciseLog(Base):
    """Physical activity record (06 §9)."""

    __tablename__ = "exercise_logs"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    occurred_at: Mapped[dt.datetime]
    local_date: Mapped[dt.date]
    activity_type: Mapped[str] = mapped_column(server_default=text("'other'"))
    duration_minutes: Mapped[SmallInt]
    intensity: Mapped[str | None]
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        CheckConstraint("duration_minutes BETWEEN 1 AND 600", name="duration_range"),
        CheckConstraint(
            "activity_type IN ('cardio', 'strength', 'walking', 'sport', 'other')",
            name="activity_type",
        ),
        CheckConstraint(
            "intensity IS NULL OR intensity IN ('low', 'moderate', 'high')",
            name="intensity",
        ),
        Index("ix_exercise_logs_user_occurred", "user_id", text("occurred_at DESC")),
        Index("ix_exercise_logs_local_date", "local_date"),
    )
