"""ORM models — the aggregation point for Alembic.

Every model module must be imported here. Alembic's ``env.py`` imports this
package and nothing else; a model that is not re-exported from this file is
invisible to autogenerate, and its table will silently never be created.

Populated in Step 1 onward (06_Database_Schema.md §19).
"""

from __future__ import annotations

from ssa.infrastructure.database.models.tracking import (
    ExerciseLog,
    MoodLog,
    SleepLog,
    StudySession,
    Subject,
)
from ssa.infrastructure.database.models.user import PrivacySettings, TelegramAccount, User

__all__ = [
    "ExerciseLog",
    "MoodLog",
    "PrivacySettings",
    "SleepLog",
    "StudySession",
    "Subject",
    "TelegramAccount",
    "User",
]
