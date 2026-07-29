"""``CreateSubject`` — add a user-defined study subject
(06_Database_Schema.md §5). ``tracking`` depends on ``identity`` (01
Architecture §5), so this checks the owning user exists before creating a
child row rather than letting a foreign-key violation surface instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.tracking.dto import CreateSubjectResult
from ssa.domain.tracking.entities import Subject

if TYPE_CHECKING:
    from ssa.application.tracking.dto import CreateSubjectRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import UserRepository
    from ssa.domain.tracking.repositories import SubjectRepository

__all__ = ["CreateSubject"]


class CreateSubject:
    """Fails with :class:`~ssa.domain.common.errors.ConflictError` for a
    case-insensitive duplicate name for the same user — including against an
    archived subject, matching ``uq_subjects_user_name`` (06 §5): reusing a
    freed name would merge two conceptually distinct subjects in historical
    charts."""

    def __init__(
        self,
        *,
        users: UserRepository,
        subjects: SubjectRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._subjects = subjects
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: CreateSubjectRequest) -> CreateSubjectResult:
        await self._users.get_by_id(request.user_id)

        now = self._clock.now()
        subject = Subject(
            user_id=request.user_id,
            name=request.name,
            colour=request.colour,
            created_at=now,
            updated_at=now,
        )
        await self._subjects.add(subject)
        if subject.id is None:  # pragma: no cover - defensive; add() always assigns the id
            raise RuntimeError("SubjectRepository.add did not assign an id")

        return CreateSubjectResult(
            subject_id=subject.id,
            user_id=subject.user_id,
            name=subject.name,
            colour=subject.colour,
            created_at=subject.created_at,
        )
