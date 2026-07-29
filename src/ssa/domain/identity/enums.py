"""Enumerations for the identity module (06_Database_Schema.md §2, §4)."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["UserStatus", "Visibility"]


class UserStatus(StrEnum):
    """Lifecycle state of a ``User`` row."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Visibility(StrEnum):
    """Who can see a profile or a user's stats. Shared domain for both
    ``profile_visibility`` and ``stats_visibility`` (06 §4)."""

    PRIVATE = "private"
    FRIENDS = "friends"
    GROUPS = "groups"
