"""DTOs crossing the tracking application boundary (02_Project_Structure.md §3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = [
    "CompleteStudySessionRequest",
    "CompleteStudySessionResult",
    "CreateSubjectRequest",
    "CreateSubjectResult",
    "GetStudyHistoryRequest",
    "GetStudyHistoryResult",
    "StartStudySessionRequest",
    "StartStudySessionResult",
    "StudyHistoryEntry",
]


class CreateSubjectRequest(BaseModel):
    user_id: int
    name: str
    colour: str | None = None


class CreateSubjectResult(BaseModel):
    subject_id: int
    user_id: int
    name: str
    colour: str | None
    created_at: datetime


class StartStudySessionRequest(BaseModel):
    user_id: int
    subject_name: str | None = None


class StartStudySessionResult(BaseModel):
    session_id: int
    user_id: int
    started_at: datetime
    subject_id: int | None = None


class CompleteStudySessionRequest(BaseModel):
    user_id: int
    focus_score: int | None = None


class CompleteStudySessionResult(BaseModel):
    session_id: int
    user_id: int
    started_at: datetime
    ended_at: datetime
    duration_minutes: int
    focus_score: int | None


class GetStudyHistoryRequest(BaseModel):
    user_id: int
    limit: int = 10


class StudyHistoryEntry(BaseModel):
    session_id: int
    subject_id: int | None
    subject_name: str | None
    started_at: datetime
    ended_at: datetime
    duration_minutes: int
    focus_score: int | None


class GetStudyHistoryResult(BaseModel):
    entries: list[StudyHistoryEntry]
