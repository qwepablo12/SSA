"""Pure tracking-domain rules — no I/O, so they can be tested exhaustively.

Overlap detection between completed sessions is deliberately absent here: it
requires reading the user's other sessions, which is a repository concern and
therefore belongs to the application layer (06 §6, Q1 rejected).
"""

from __future__ import annotations

from datetime import timedelta

__all__ = ["MAX_STUDY_SESSION_DURATION"]

# The database's own ceiling (06 §6, ck_study_sessions_max_duration) is 12
# hours and exists purely as a corruption backstop — it catches a forgotten
# timer, not policy. This is the actual product rule from Phase 1: a database
# constraint restating it at exactly 8 hours would mean every future tweak to
# this number needs a migration, so it is enforced here instead, one line from
# being changed.
MAX_STUDY_SESSION_DURATION = timedelta(hours=8)
