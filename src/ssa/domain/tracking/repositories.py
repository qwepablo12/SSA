"""Repository protocols for the tracking module (02_Project_Structure.md §2).

Declared in the domain, implemented in
``infrastructure/database/repositories``. ``SleepLog``, ``MoodLog`` and
``ExerciseLog`` expose no ``get_by_id``/``update``: the entities themselves
have no mutator methods (06 §7-9 — they are append-only logs), so there is
nothing yet for a repository to update.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from ssa.domain.tracking.entities import (
        ExerciseLog,
        MoodLog,
        SleepLog,
        StudySession,
        Subject,
    )

__all__ = [
    "ExerciseLogRepository",
    "MoodLogRepository",
    "SleepLogRepository",
    "StudySessionRepository",
    "SubjectRepository",
]


class SubjectRepository(Protocol):
    """Persistence port for :class:`~ssa.domain.tracking.entities.Subject`."""

    async def add(self, subject: Subject) -> None: ...

    async def get_by_id(self, subject_id: int) -> Subject: ...

    async def find_by_id(self, subject_id: int) -> Subject | None: ...

    async def list_for_user(self, user_id: int, *, include_archived: bool = False) -> list[Subject]:
        """Defaults to the non-archived set — the picker's dominant read
        pattern (06 §5, ``ix_subjects_user_active``)."""
        ...

    async def find_by_name_for_user(self, user_id: int, name: str) -> Subject | None:
        """Case-insensitive lookup scoped to the owning user and to
        non-archived subjects (``uq_subjects_user_name``) — resolves the free
        text typed into ``/study <subject>``, so a name never leaks whether it
        belongs to someone else."""
        ...

    async def update(self, subject: Subject) -> None: ...


class StudySessionRepository(Protocol):
    """Persistence port for
    :class:`~ssa.domain.tracking.entities.StudySession`."""

    async def add(self, session: StudySession) -> None: ...

    async def get_by_id(self, session_id: int) -> StudySession: ...

    async def find_by_id(self, session_id: int) -> StudySession | None: ...

    async def find_active_for_user(self, user_id: int) -> StudySession | None:
        """The at most one ``in_progress`` session the schema enforces
        structurally (06 §6, ``uq_study_sessions_one_active``)."""
        ...

    async def list_for_user(
        self, user_id: int, *, since: date | None = None, until: date | None = None
    ) -> list[StudySession]:
        """Most recent first — the dominant read pattern (06 §6,
        ``ix_study_sessions_user_started``)."""
        ...

    async def update(self, session: StudySession) -> None: ...


class SleepLogRepository(Protocol):
    """Persistence port for :class:`~ssa.domain.tracking.entities.SleepLog`."""

    async def add(self, log: SleepLog) -> None: ...

    async def find_for_user_on_date(self, user_id: int, local_date: date) -> SleepLog | None:
        """The at most one row per user per night (06 §7,
        ``uq_sleep_logs_user_date``)."""
        ...


class MoodLogRepository(Protocol):
    """Persistence port for :class:`~ssa.domain.tracking.entities.MoodLog`."""

    async def add(self, log: MoodLog) -> None: ...

    async def list_for_user_on_date(self, user_id: int, local_date: date) -> list[MoodLog]:
        """Multiple entries per day are normal (06 §8)."""
        ...


class ExerciseLogRepository(Protocol):
    """Persistence port for
    :class:`~ssa.domain.tracking.entities.ExerciseLog`."""

    async def add(self, log: ExerciseLog) -> None: ...

    async def list_for_user_on_date(self, user_id: int, local_date: date) -> list[ExerciseLog]: ...
