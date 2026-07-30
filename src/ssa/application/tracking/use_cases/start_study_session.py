"""``StartStudySession`` — begin tracking a new study session
(06_Database_Schema.md §6). At most one session may be ``in_progress`` per
user at a time, enforced structurally by ``uq_study_sessions_one_active`` —
checked here first so a second start gets a clean :class:`ConflictError`
instead of a raw constraint violation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ssa.application.common.decorators import transactional
from ssa.application.tracking.dto import StartStudySessionResult
from ssa.domain.common.errors import ConflictError, NotFoundError
from ssa.domain.tracking.entities import StudySession

if TYPE_CHECKING:
    from ssa.application.tracking.dto import StartStudySessionRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import UserRepository
    from ssa.domain.tracking.repositories import StudySessionRepository, SubjectRepository

__all__ = ["StartStudySession"]


class StartStudySession:
    def __init__(
        self,
        *,
        users: UserRepository,
        study_sessions: StudySessionRepository,
        subjects: SubjectRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._study_sessions = study_sessions
        self._subjects = subjects
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: StartStudySessionRequest) -> StartStudySessionResult:
        user = await self._users.get_by_id(request.user_id)

        active = await self._study_sessions.find_active_for_user(request.user_id)
        if active is not None:
            raise ConflictError(
                "A study session is already in progress",
                user_id=request.user_id,
                session_id=active.id,
            )

        subject_id: int | None = None
        if request.subject_name is not None:
            subject = await self._subjects.find_by_name_for_user(
                request.user_id, request.subject_name
            )
            if subject is None:
                raise NotFoundError(
                    "Subject not found",
                    user_id=request.user_id,
                    subject_name=request.subject_name,
                )
            subject_id = subject.id

        now = self._clock.now()
        session = StudySession(
            user_id=request.user_id,
            subject_id=subject_id,
            started_at=now,
            local_date=self._clock.today_in(ZoneInfo(user.timezone)),
            created_at=now,
            updated_at=now,
        )
        await self._study_sessions.add(session)
        if session.id is None:  # pragma: no cover - defensive; add() always assigns the id
            raise RuntimeError("StudySessionRepository.add did not assign an id")

        return StartStudySessionResult(
            session_id=session.id,
            user_id=session.user_id,
            started_at=session.started_at,
            subject_id=session.subject_id,
        )
