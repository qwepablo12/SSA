"""Enumerations for the tracking module (06_Database_Schema.md Part II)."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ExerciseActivityType", "ExerciseIntensity", "SessionStatus", "SessionType"]


class SessionStatus(StrEnum):
    """Lifecycle state of a ``StudySession`` (06 §6)."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    DISCARDED = "discarded"


class SessionType(StrEnum):
    FOCUS = "focus"
    REVIEW = "review"
    PRACTICE = "practice"
    READING = "reading"
    OTHER = "other"


class ExerciseActivityType(StrEnum):
    CARDIO = "cardio"
    STRENGTH = "strength"
    WALKING = "walking"
    SPORT = "sport"
    OTHER = "other"


class ExerciseIntensity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
