"""Dishka wiring for the infrastructure layer (03_Technology_Decisions.md
ADR-005, 01_Architecture.md §7.3).

Two scopes, matching the session-per-request rule:

* ``APP`` — the session factory and the clock, built once per process.
* ``REQUEST`` — the unit of work and every repository, built once per unit
  of work and torn down (rolled back if uncommitted) with it.

The session factory itself is supplied from outside via :func:`from_context`
rather than built here from ``Settings`` — ``Settings.load()`` only ever runs
at a process entrypoint (``apps/*/main.py``, Alembic's ``env.py``, the test
harness), never inside a library module, so the engine's lifecycle belongs to
whoever calls that entrypoint. This is also what lets a test hand in a
sessionmaker bound to an already-open, rolled-back transaction instead of a
fresh connection.

Every dependency is provided under its **domain protocol** type, never the
concrete class, so :mod:`ssa.application` never has to know a SQLAlchemy
repository exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterable

from dishka import Provider, Scope, alias, from_context, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ssa.domain.common.protocols import Clock, UnitOfWork
from ssa.domain.identity.repositories import (
    PrivacySettingsRepository,
    TelegramAccountRepository,
    UserRepository,
)
from ssa.domain.tracking.repositories import (
    ExerciseLogRepository,
    MoodLogRepository,
    SleepLogRepository,
    StudySessionRepository,
    SubjectRepository,
)
from ssa.infrastructure.clock import SystemClock
from ssa.infrastructure.database.repositories import (
    SqlAlchemyExerciseLogRepository,
    SqlAlchemyMoodLogRepository,
    SqlAlchemyPrivacySettingsRepository,
    SqlAlchemySleepLogRepository,
    SqlAlchemyStudySessionRepository,
    SqlAlchemySubjectRepository,
    SqlAlchemyTelegramAccountRepository,
    SqlAlchemyUserRepository,
)
from ssa.infrastructure.database.uow import SqlAlchemyUnitOfWork

__all__ = ["InfrastructureProvider"]


class InfrastructureProvider(Provider):
    session_factory = from_context(provides=async_sessionmaker[AsyncSession], scope=Scope.APP)

    @provide(scope=Scope.APP)
    def get_clock(self) -> Clock:
        return SystemClock()

    @provide(scope=Scope.REQUEST)
    async def get_unit_of_work(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> AsyncIterable[SqlAlchemyUnitOfWork]:
        uow = SqlAlchemyUnitOfWork(session_factory)
        async with uow:
            yield uow

    unit_of_work = alias(source=SqlAlchemyUnitOfWork, provides=UnitOfWork)

    @provide(scope=Scope.REQUEST)
    def get_session(self, uow: SqlAlchemyUnitOfWork) -> AsyncSession:
        return uow.session

    # Explicit factories rather than Dishka's `provide(ConcreteClass)`
    # shorthand: that shorthand needs a real (non-``TYPE_CHECKING``) import of
    # ``AsyncSession`` on each repository's ``__init__`` to resolve its type
    # hints at container-build time, which would force every repository to
    # carry a Dishka-shaped import just for this. An explicit factory keeps
    # each repository exactly as framework-agnostic as it already is.

    @provide(scope=Scope.REQUEST)
    def get_user_repository(self, session: AsyncSession) -> UserRepository:
        return SqlAlchemyUserRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_telegram_account_repository(self, session: AsyncSession) -> TelegramAccountRepository:
        return SqlAlchemyTelegramAccountRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_privacy_settings_repository(self, session: AsyncSession) -> PrivacySettingsRepository:
        return SqlAlchemyPrivacySettingsRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_subject_repository(self, session: AsyncSession) -> SubjectRepository:
        return SqlAlchemySubjectRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_study_session_repository(self, session: AsyncSession) -> StudySessionRepository:
        return SqlAlchemyStudySessionRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_sleep_log_repository(self, session: AsyncSession) -> SleepLogRepository:
        return SqlAlchemySleepLogRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_mood_log_repository(self, session: AsyncSession) -> MoodLogRepository:
        return SqlAlchemyMoodLogRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_exercise_log_repository(self, session: AsyncSession) -> ExerciseLogRepository:
        return SqlAlchemyExerciseLogRepository(session)
