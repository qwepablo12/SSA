"""The single domain exception hierarchy (01_Architecture.md §7.2).

Every layer boundary translates these once: the bot renders a friendly message,
the API maps to an HTTP status. Infrastructure exceptions —
``sqlalchemy.IntegrityError``, ``redis.RedisError``, ``TelegramAPIError`` — are
caught in the infrastructure layer and re-raised as one of these. A SQLAlchemy
exception reaching a handler is a bug in the repository that let it through.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ConflictError",
    "ExternalServiceError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitedError",
    "SSAError",
    "ValidationError",
]


class SSAError(Exception):
    """Base class for every expected failure in the system.

    ``details`` carries structured context for logs. It is never rendered to a
    user directly — presentation is the boundary's job, not the error's.
    """

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r}, {self.details!r})"


class ValidationError(SSAError):
    """Input violates a domain rule. Bot: correction. API: 422."""


class NotFoundError(SSAError):
    """A requested entity does not exist. Bot: "I couldn't find that". API: 404."""


class PermissionDeniedError(SSAError):
    """The caller may not see or change this. Bot: "That's private". API: 403."""


class ConflictError(SSAError):
    """The operation conflicts with existing state.

    Raised for the invariants the database also guards — a second in-progress
    study session, a duplicate subject name — and for the overlap check that,
    per the approved Q1, lives only in the application layer.
    """


class RateLimitedError(SSAError):
    """The caller is going too fast. Bot: silent backoff. API: 429."""


class ExternalServiceError(SSAError):
    """A dependency outside our control failed. Bot: "try again shortly". API: 502."""
