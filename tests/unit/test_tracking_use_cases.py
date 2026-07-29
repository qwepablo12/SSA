"""Unit tests for the tracking application use cases. No database — the user
repository dependency is the same hand-rolled fake used by the identity use
case tests (``tests/unit/fakes.py``).
"""

from __future__ import annotations

import uuid

import pytest

from ssa.application.tracking.dto import CreateSubjectRequest
from ssa.application.tracking.use_cases.create_subject import CreateSubject
from ssa.domain.common.errors import ConflictError, NotFoundError, ValidationError
from ssa.domain.identity.entities import User
from ssa.domain.identity.enums import UserStatus
from tests.unit.fakes import FakeClock, FakeSubjectRepository, FakeUnitOfWork, FakeUserRepository


async def _persisted_user(users: FakeUserRepository, clock: FakeClock) -> int:
    user = User(
        public_id=uuid.uuid4(),
        timezone="UTC",
        locale="en",
        status=UserStatus.ACTIVE,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    await users.add(user)
    assert user.id is not None
    return user.id


class TestCreateSubject:
    async def test_creates_a_subject_for_an_existing_user(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        user_id = await _persisted_user(users, clock)
        uow = FakeUnitOfWork()
        use_case = CreateSubject(
            users=users, subjects=FakeSubjectRepository(), clock=clock, uow=uow
        )

        result = await use_case.execute(
            CreateSubjectRequest(user_id=user_id, name="Maths", colour="#FF00FF")
        )

        assert result.subject_id is not None
        assert result.name == "Maths"
        assert result.colour == "#FF00FF"
        assert uow.committed is True

    async def test_raises_not_found_for_an_unknown_user(self) -> None:
        use_case = CreateSubject(
            users=FakeUserRepository(),
            subjects=FakeSubjectRepository(),
            clock=FakeClock(),
            uow=FakeUnitOfWork(),
        )

        with pytest.raises(NotFoundError):
            await use_case.execute(CreateSubjectRequest(user_id=999, name="Maths"))

    async def test_raises_conflict_for_a_case_insensitive_duplicate_name(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        user_id = await _persisted_user(users, clock)
        subjects = FakeSubjectRepository()
        use_case = CreateSubject(users=users, subjects=subjects, clock=clock, uow=FakeUnitOfWork())
        await use_case.execute(CreateSubjectRequest(user_id=user_id, name="Maths"))

        with pytest.raises(ConflictError):
            await use_case.execute(CreateSubjectRequest(user_id=user_id, name="maths"))

    async def test_rejects_an_invalid_colour(self) -> None:
        users = FakeUserRepository()
        clock = FakeClock()
        user_id = await _persisted_user(users, clock)
        use_case = CreateSubject(
            users=users, subjects=FakeSubjectRepository(), clock=clock, uow=FakeUnitOfWork()
        )

        with pytest.raises(ValidationError):
            await use_case.execute(
                CreateSubjectRequest(user_id=user_id, name="Maths", colour="blue")
            )
