"""Real-time implementation of the :class:`~ssa.domain.common.protocols.Clock` port."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

__all__ = ["SystemClock"]


class SystemClock:
    """Wall-clock time, always timezone-aware and always UTC.

    Deliberately returns an aware datetime: a naive one would be silently
    coerced by asyncpg into whatever the server thinks local time is, which is
    exactly the class of bug the TIMESTAMPTZ-everywhere rule exists to prevent
    (06_Database_Schema.md §15).
    """

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today_in(self, timezone: ZoneInfo) -> date:
        return self.now().astimezone(timezone).date()
