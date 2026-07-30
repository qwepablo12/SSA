"""``CompleteStudySession`` — finish the user's in-progress study session
(06_Database_Schema.md §6, Q1).

Resolves the session via ``find_active_for_user`` rather than taking a
``session_id``: the schema guarantees at most one ``in_progress`` session per
user (``uq_study_sessions_one_active``), so there is never an ambiguity about
which session ``/done`` refers to, and the bot never needs to track one.

Overlap against the user's other completed sessions is a *checked*, not
*guaranteed*, invariant (Q1 rejected an exclusion constraint on
``study_sessions`` — no ``btree_gist`` extension). A concurrent double-write
can still slip through; mitigated by the partial unique index above (the
realistic race is narrow) and by the nightly rollup's data-quality check.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.tracking.dto import CompleteStudySessionResult
from ssa.domain.common.errors import ConflictError, NotFoundError
from ssa.domain.tracking.enums import SessionStatus

if TYPE_CHECKING:
    from datetime import datetime

    from ssa.application.tracking.dto import CompleteStudySessionRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.tracking.entities import StudySession
    from ssa.domain.tracking.repositories import StudySessionRepository

__all__ = ["CompleteStudySession"]


class CompleteStudySession:
    def __init__(
        self,
        *,
        study_sessions: StudySessionRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._study_sessions = study_sessions
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: CompleteStudySessionRequest) -> CompleteStudySessionResult:
        session = await self._study_sessions.find_active_for_user(request.user_id)
        if session is None:
            raise NotFoundError("No study session in progress", user_id=request.user_id)
        if (
            session.id is None
        ):  # pragma: no cover - defensive; find_active_for_user returns persisted rows
            raise RuntimeError(
                "StudySessionRepository.find_active_for_user returned a session with no id"
            )

        ended_at = self._clock.now()
        session.complete(ended_at=ended_at, focus_score=request.focus_score)

        await self._check_no_overlap(session, ended_at=ended_at)
        await self._study_sessions.update(session)

        duration_minutes = int((ended_at - session.started_at).total_seconds() // 60)
        return CompleteStudySessionResult(
            session_id=session.id,
            user_id=session.user_id,
            started_at=session.started_at,
            ended_at=ended_at,
            duration_minutes=duration_minutes,
            focus_score=session.focus_score,
        )

    async def _check_no_overlap(self, session: StudySession, *, ended_at: datetime) -> None:
        # One extra day back covers a session that started the previous local
        # day and ended after midnight; anything further is already excluded
        # by MAX_STUDY_SESSION_DURATION on both sessions.
        others = await self._study_sessions.list_for_user(
            session.user_id,
            since=session.local_date - timedelta(days=1),
            until=session.local_date,
        )
        for other in others:
            if other.id == session.id or other.status is not SessionStatus.COMPLETED:
                continue
            if other.ended_at is None:  # pragma: no cover - defensive; COMPLETED always has one
                continue
            if session.started_at < other.ended_at and other.started_at < ended_at:
                raise ConflictError(
                    "Session overlaps with an existing completed session",
                    session_id=session.id,
                    conflicting_session_id=other.id,
                )
