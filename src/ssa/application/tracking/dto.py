"""DTOs crossing the tracking application boundary (02_Project_Structure.md §3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = ["CreateSubjectRequest", "CreateSubjectResult"]


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
