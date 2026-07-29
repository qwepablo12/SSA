"""Tracking domain entities (06_Database_Schema.md Part II)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ssa.domain.common.entity import Entity
from ssa.domain.common.errors import ValidationError
from ssa.domain.tracking.enums import (
    ExerciseActivityType,
    ExerciseIntensity,
    SessionStatus,
    SessionType,
)
from ssa.domain.tracking.rules import MAX_STUDY_SESSION_DURATION

if TYPE_CHECKING:
    from datetime import date, datetime

__all__ = ["ExerciseLog", "MoodLog", "SleepLog", "StudySession", "Subject"]

_COLOUR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_scale(field_name: str, value: int | None) -> None:
    """Every 1-5 self-reported scale in this module shares this check."""
    if value is not None and not (1 <= value <= 5):
        raise ValidationError(f"{field_name} must be between 1 and 5", **{field_name: value})


@dataclass(eq=False)
class Subject(Entity):
    """A user-defined study subject — per-user, not a shared catalogue (06 §5)."""

    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    colour: str | None = None
    is_archived: bool = False

    def __post_init__(self) -> None:
        self._validate_name(self.name)
        if self.colour is not None and not _COLOUR_RE.match(self.colour):
            raise ValidationError("colour must be a #RRGGBB hex value", colour=self.colour)

    @staticmethod
    def _validate_name(name: str) -> None:
        if not (1 <= len(name.strip()) <= 100):
            raise ValidationError("name must be 1-100 characters", name=name)

    def rename(self, name: str) -> None:
        self._validate_name(name)
        self.name = name

    def archive(self) -> None:
        """Hide from pickers while retaining history (06 §5) — subjects are
        never hard-deleted by the domain; ``study_sessions.subject_id`` is
        what ``ON DELETE SET NULL`` would touch, and that path never runs
        here."""
        self.is_archived = True

    def restore(self) -> None:
        self.is_archived = False


@dataclass(eq=False)
class StudySession(Entity):
    """The primary behavioural record (06 §6)."""

    user_id: int
    started_at: datetime
    local_date: date
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    subject_id: int | None = None
    status: SessionStatus = SessionStatus.IN_PROGRESS
    ended_at: datetime | None = None
    planned_minutes: int | None = None
    focus_score: int | None = None
    session_type: SessionType = SessionType.FOCUS
    interruption_count: int = 0
    notes: str | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if (self.status is SessionStatus.IN_PROGRESS) != (self.ended_at is None):
            raise ValidationError(
                "an in_progress session must have no end time, and every other "
                "status must have one",
                status=self.status,
            )
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValidationError("ended_at must be after started_at")
        _validate_scale("focus_score", self.focus_score)
        if self.interruption_count < 0:
            raise ValidationError("interruption_count cannot be negative")
        if self.planned_minutes is not None and self.planned_minutes <= 0:
            raise ValidationError("planned_minutes must be positive")

    def _end(self, *, status: SessionStatus, ended_at: datetime) -> None:
        if self.status is not SessionStatus.IN_PROGRESS:
            raise ValidationError("only an in_progress session can be ended", status=self.status)
        if ended_at - self.started_at > MAX_STUDY_SESSION_DURATION:
            raise ValidationError(
                "session exceeds the maximum allowed duration",
                max_duration=MAX_STUDY_SESSION_DURATION,
            )
        self.status = status
        self.ended_at = ended_at
        self._validate()

    def complete(self, *, ended_at: datetime, focus_score: int | None = None) -> None:
        """Finish the session normally.

        Overlap against the user's other completed sessions is a checked, not
        guaranteed, invariant — it requires reading other rows, so it is the
        application layer's job (06 §6, Q1 rejected), not this method's.
        """
        self._end(status=SessionStatus.COMPLETED, ended_at=ended_at)
        self.focus_score = focus_score

    def abandon(self, *, ended_at: datetime) -> None:
        self._end(status=SessionStatus.ABANDONED, ended_at=ended_at)

    def discard(self, *, ended_at: datetime) -> None:
        """Void a mistaken in-progress session (e.g. started by accident)."""
        self._end(status=SessionStatus.DISCARDED, ended_at=ended_at)

    def record_interruption(self) -> None:
        self.interruption_count += 1

    def soft_delete(self, *, at: datetime) -> None:
        """User-initiated deletion is soft — undo is worth having, and the
        row is purged permanently 30 days later by a maintenance job (06 §6,
        Q4), not by the domain."""
        self.deleted_at = at


@dataclass(eq=False)
class SleepLog(Entity):
    """Daily sleep record, attributed to the wake date (06 §7, Q5)."""

    user_id: int
    local_date: date
    duration_minutes: int
    created_at: datetime
    updated_at: datetime
    id: int | None = None
    bedtime_at: datetime | None = None
    wake_at: datetime | None = None
    quality: int | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.duration_minutes <= 1440):
            raise ValidationError(
                "duration_minutes must be between 0 and 1440",
                duration_minutes=self.duration_minutes,
            )
        _validate_scale("quality", self.quality)
        if (
            self.bedtime_at is not None
            and self.wake_at is not None
            and self.wake_at <= self.bedtime_at
        ):
            raise ValidationError("wake_at must be after bedtime_at")


@dataclass(eq=False)
class MoodLog(Entity):
    """Point-in-time affect record; multiple entries per day are normal (06 §8)."""

    user_id: int
    recorded_at: datetime
    local_date: date
    mood: int
    created_at: datetime
    id: int | None = None
    energy: int | None = None
    stress: int | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        _validate_scale("mood", self.mood)
        _validate_scale("energy", self.energy)
        _validate_scale("stress", self.stress)
        if self.note is not None and len(self.note) > 1000:
            raise ValidationError("note must be at most 1000 characters")


@dataclass(eq=False)
class ExerciseLog(Entity):
    """Physical activity record (06 §9)."""

    user_id: int
    occurred_at: datetime
    local_date: date
    duration_minutes: int
    created_at: datetime
    id: int | None = None
    activity_type: ExerciseActivityType = ExerciseActivityType.OTHER
    intensity: ExerciseIntensity | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.duration_minutes <= 600):
            raise ValidationError(
                "duration_minutes must be between 1 and 600",
                duration_minutes=self.duration_minutes,
            )
