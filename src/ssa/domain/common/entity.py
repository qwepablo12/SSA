"""Base class for domain entities with a surrogate primary key.

Entities are compared and hashed by identity, not by the value of their other
fields — two ``StudySession`` instances with the same ``id`` are the same
session even if one holds staler field values. Before an entity is persisted,
``id`` is ``None`` (the database assigns it on insert), so equality falls back
to object identity in that state — two freshly constructed, not-yet-saved
entities are never accidentally treated as the same row.

Not every entity uses this base: ``TelegramAccount`` and ``PrivacySettings``
are keyed by ``user_id`` rather than a surrogate id (06_Database_Schema.md
§3), so their identity is never "pending" the way a surrogate key is, and they
use plain dataclass value equality instead.
"""

from __future__ import annotations

__all__ = ["Entity"]


class Entity:
    """Mixin supplying identity-based ``__eq__``/``__hash__`` for a subclass
    that declares its own ``id: int | None`` dataclass field."""

    id: int | None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity) or type(other) is not type(self):
            return NotImplemented
        if self.id is None or other.id is None:
            return self is other
        return self.id == other.id

    def __hash__(self) -> int:
        if self.id is None:
            return object.__hash__(self)
        return hash((type(self), self.id))
