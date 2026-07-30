"""``GetStudyHistory`` — list a user's most recent completed study sessions
(06_Database_Schema.md §6), newest first.

Read-only, unlike every other use case in this module: there is no
``@transactional``/``UnitOfWork`` here because there is nothing to commit —
``@transactional`` marks the single commit point a *write* use case owns
(``application/common/decorators.py``), and a pure query has none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.application.tracking.dto import GetStudyHistoryResult, StudyHistoryEntry
from ssa.domain.tracking.enums import SessionStatus

if TYPE_CHECKING:
    from ssa.application.tracking.dto import GetStudyHistoryRequest
    from ssa.domain.identity.repositories import UserRepository
    from ssa.domain.tracking.repositories import StudySessionRepository, SubjectRepository

__all__ = ["GetStudyHistory"]


class GetStudyHistory:
    def __init__(
        self,
        *,
        users: UserRepository,
        study_sessions: StudySessionRepository,
        subjects: SubjectRepository,
    ) -> None:
        self._users = users
        self._study_sessions = study_sessions
        self._subjects = subjects

    async def execute(self, request: GetStudyHistoryRequest) -> GetStudyHistoryResult:
        await self._users.get_by_id(request.user_id)

        sessions = await self._study_sessions.list_for_user(
            request.user_id, status=SessionStatus.COMPLETED, limit=request.limit
        )

        # One find_by_id per distinct subject rather than a bulk/join lookup:
        # acceptable while `limit` stays small (default 10, no pagination
        # yet). Revisit with a bulk SubjectRepository lookup or a joined
        # history query if/when the cap grows or pagination lands.
        subject_names: dict[int, str] = {}
        for session in sessions:
            if session.subject_id is None or session.subject_id in subject_names:
                continue
            subject = await self._subjects.find_by_id(session.subject_id)
            if subject is not None:
                subject_names[session.subject_id] = subject.name

        entries: list[StudyHistoryEntry] = []
        for session in sessions:
            if session.id is None:  # pragma: no cover - defensive; queried rows are persisted
                raise RuntimeError("StudySessionRepository.list_for_user returned an unsaved row")
            if session.ended_at is None:  # pragma: no cover - defensive; COMPLETED always has one
                raise RuntimeError("A completed study session has no ended_at")
            duration_minutes = int((session.ended_at - session.started_at).total_seconds() // 60)
            entries.append(
                StudyHistoryEntry(
                    session_id=session.id,
                    subject_id=session.subject_id,
                    subject_name=(
                        subject_names.get(session.subject_id)
                        if session.subject_id is not None
                        else None
                    ),
                    started_at=session.started_at,
                    ended_at=session.ended_at,
                    duration_minutes=duration_minutes,
                    focus_score=session.focus_score,
                )
            )

        return GetStudyHistoryResult(entries=entries)
