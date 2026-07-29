"""SQLAlchemy implementations of the domain repository protocols.

One module per entity, each implementing the corresponding protocol in
``domain.<module>.repositories`` structurally (``Protocol`` — no base class,
no registration).
"""

from __future__ import annotations

from ssa.infrastructure.database.repositories.exercise_log_repository import (
    SqlAlchemyExerciseLogRepository,
)
from ssa.infrastructure.database.repositories.mood_log_repository import (
    SqlAlchemyMoodLogRepository,
)
from ssa.infrastructure.database.repositories.privacy_settings_repository import (
    SqlAlchemyPrivacySettingsRepository,
)
from ssa.infrastructure.database.repositories.sleep_log_repository import (
    SqlAlchemySleepLogRepository,
)
from ssa.infrastructure.database.repositories.study_session_repository import (
    SqlAlchemyStudySessionRepository,
)
from ssa.infrastructure.database.repositories.subject_repository import (
    SqlAlchemySubjectRepository,
)
from ssa.infrastructure.database.repositories.telegram_account_repository import (
    SqlAlchemyTelegramAccountRepository,
)
from ssa.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository

__all__ = [
    "SqlAlchemyExerciseLogRepository",
    "SqlAlchemyMoodLogRepository",
    "SqlAlchemyPrivacySettingsRepository",
    "SqlAlchemySleepLogRepository",
    "SqlAlchemyStudySessionRepository",
    "SqlAlchemySubjectRepository",
    "SqlAlchemyTelegramAccountRepository",
    "SqlAlchemyUserRepository",
]
