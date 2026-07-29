"""ORM model ⇄ domain entity mappers for the tracking module (ADR-004).

See ``mappers/identity.py`` for the three-function-per-entity convention.
``SleepLog``, ``MoodLog`` and ``ExerciseLog`` have no ``update_*_model``: the
domain entities expose no mutator methods (06 §7-9), so there is nothing yet
for a repository to write back.
"""

from __future__ import annotations

from ssa.domain.tracking.entities import ExerciseLog, MoodLog, SleepLog, StudySession, Subject
from ssa.domain.tracking.enums import (
    ExerciseActivityType,
    ExerciseIntensity,
    SessionStatus,
    SessionType,
)
from ssa.infrastructure.database import models

__all__ = [
    "exercise_log_to_domain",
    "mood_log_to_domain",
    "new_exercise_log_model",
    "new_mood_log_model",
    "new_sleep_log_model",
    "new_study_session_model",
    "new_subject_model",
    "sleep_log_to_domain",
    "study_session_to_domain",
    "subject_to_domain",
    "update_study_session_model",
    "update_subject_model",
]


def subject_to_domain(model: models.Subject) -> Subject:
    return Subject(
        id=model.id,
        user_id=model.user_id,
        name=model.name,
        created_at=model.created_at,
        updated_at=model.updated_at,
        colour=model.colour,
        is_archived=model.is_archived,
    )


def new_subject_model(subject: Subject) -> models.Subject:
    return models.Subject(
        user_id=subject.user_id,
        name=subject.name,
        colour=subject.colour,
        is_archived=subject.is_archived,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


def update_subject_model(subject: Subject, model: models.Subject) -> None:
    model.name = subject.name
    model.colour = subject.colour
    model.is_archived = subject.is_archived


def study_session_to_domain(model: models.StudySession) -> StudySession:
    return StudySession(
        id=model.id,
        user_id=model.user_id,
        started_at=model.started_at,
        local_date=model.local_date,
        created_at=model.created_at,
        updated_at=model.updated_at,
        subject_id=model.subject_id,
        status=SessionStatus(model.status),
        ended_at=model.ended_at,
        planned_minutes=model.planned_minutes,
        focus_score=model.focus_score,
        session_type=SessionType(model.session_type),
        interruption_count=model.interruption_count,
        notes=model.notes,
        deleted_at=model.deleted_at,
    )


def new_study_session_model(session: StudySession) -> models.StudySession:
    """``duration_seconds`` is a generated column (``models/tracking.py``) and
    is never set here — PostgreSQL computes it from ``started_at``/``ended_at``."""
    return models.StudySession(
        user_id=session.user_id,
        subject_id=session.subject_id,
        status=session.status.value,
        started_at=session.started_at,
        ended_at=session.ended_at,
        local_date=session.local_date,
        planned_minutes=session.planned_minutes,
        focus_score=session.focus_score,
        session_type=session.session_type.value,
        interruption_count=session.interruption_count,
        notes=session.notes,
        created_at=session.created_at,
        updated_at=session.updated_at,
        deleted_at=session.deleted_at,
    )


def update_study_session_model(session: StudySession, model: models.StudySession) -> None:
    model.subject_id = session.subject_id
    model.status = session.status.value
    model.ended_at = session.ended_at
    model.focus_score = session.focus_score
    model.interruption_count = session.interruption_count
    model.notes = session.notes
    model.deleted_at = session.deleted_at


def sleep_log_to_domain(model: models.SleepLog) -> SleepLog:
    return SleepLog(
        id=model.id,
        user_id=model.user_id,
        local_date=model.local_date,
        duration_minutes=model.duration_minutes,
        created_at=model.created_at,
        updated_at=model.updated_at,
        bedtime_at=model.bedtime_at,
        wake_at=model.wake_at,
        quality=model.quality,
    )


def new_sleep_log_model(log: SleepLog) -> models.SleepLog:
    return models.SleepLog(
        user_id=log.user_id,
        local_date=log.local_date,
        duration_minutes=log.duration_minutes,
        bedtime_at=log.bedtime_at,
        wake_at=log.wake_at,
        quality=log.quality,
        created_at=log.created_at,
        updated_at=log.updated_at,
    )


def mood_log_to_domain(model: models.MoodLog) -> MoodLog:
    return MoodLog(
        id=model.id,
        user_id=model.user_id,
        recorded_at=model.recorded_at,
        local_date=model.local_date,
        mood=model.mood,
        created_at=model.created_at,
        energy=model.energy,
        stress=model.stress,
        note=model.note,
    )


def new_mood_log_model(log: MoodLog) -> models.MoodLog:
    return models.MoodLog(
        user_id=log.user_id,
        recorded_at=log.recorded_at,
        local_date=log.local_date,
        mood=log.mood,
        energy=log.energy,
        stress=log.stress,
        note=log.note,
        created_at=log.created_at,
    )


def exercise_log_to_domain(model: models.ExerciseLog) -> ExerciseLog:
    return ExerciseLog(
        id=model.id,
        user_id=model.user_id,
        occurred_at=model.occurred_at,
        local_date=model.local_date,
        duration_minutes=model.duration_minutes,
        created_at=model.created_at,
        activity_type=ExerciseActivityType(model.activity_type),
        intensity=ExerciseIntensity(model.intensity) if model.intensity is not None else None,
    )


def new_exercise_log_model(log: ExerciseLog) -> models.ExerciseLog:
    return models.ExerciseLog(
        user_id=log.user_id,
        occurred_at=log.occurred_at,
        local_date=log.local_date,
        activity_type=log.activity_type.value,
        duration_minutes=log.duration_minutes,
        intensity=log.intensity.value if log.intensity is not None else None,
        created_at=log.created_at,
    )
