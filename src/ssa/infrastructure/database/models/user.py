"""ORM models for the identity module: ``users``, ``telegram_accounts``,
``privacy_settings`` (06_Database_Schema.md Part I).

These are persistence models, not domain entities (ADR-004) — see
``ssa.domain.identity.entities`` for the rich, framework-free counterparts and
the eventual ``infrastructure/database/mappers/`` for the translation between
the two.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from ssa.infrastructure.database.base import Base
from ssa.infrastructure.database.types import BigIntPK, CreatedAt, PublicUUID, UpdatedAt

__all__ = ["PrivacySettings", "TelegramAccount", "User"]


class User(Base):
    """The internal identity record. Deliberately Telegram-free (D4)."""

    __tablename__ = "users"

    id: Mapped[BigIntPK]
    public_id: Mapped[PublicUUID]
    timezone: Mapped[str] = mapped_column(server_default=text("'UTC'"))
    locale: Mapped[str] = mapped_column(server_default=text("'en'"))
    display_name: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    onboarding_completed_at: Mapped[dt.datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[dt.datetime | None]

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'deleted')", name="status"),
        CheckConstraint("length(trim(timezone)) > 0", name="timezone_not_blank"),
        CheckConstraint(
            "display_name IS NULL OR length(display_name) BETWEEN 1 AND 64",
            name="display_name_length",
        ),
        # Partial: only rows the erasure sweep touches, so the index stays
        # near-empty rather than duplicating every row in the table.
        Index(
            "ix_users_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )


class TelegramAccount(Base):
    """Telegram-specific identity, isolated so a second login provider is a
    new table rather than a schema-wide migration (06 §3, D4).

    Keyed by ``user_id`` rather than a surrogate id: the relationship is
    genuinely 1:1, and a surrogate key would let two Telegram accounts attach
    to one user at the schema level — a state the application would then have
    to police instead of the database ruling out structurally.
    """

    __tablename__ = "telegram_accounts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_id: Mapped[int] = mapped_column(unique=True)
    chat_id: Mapped[int]
    telegram_username: Mapped[str | None]
    language_code: Mapped[str | None]
    linked_at: Mapped[CreatedAt]
    last_seen_at: Mapped[dt.datetime | None]

    __table_args__ = (
        CheckConstraint("telegram_id > 0", name="telegram_id_positive"),
        CheckConstraint(
            "telegram_username IS NULL OR length(telegram_username) <= 32",
            name="username_length",
        ),
    )


class PrivacySettings(Base):
    """Per-user privacy and consent state, present from the first user row
    (06 §4). Same 1:1-by-``user_id`` reasoning as :class:`TelegramAccount`."""

    __tablename__ = "privacy_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    profile_visibility: Mapped[str] = mapped_column(server_default=text("'private'"))
    stats_visibility: Mapped[str] = mapped_column(server_default=text("'private'"))
    leaderboard_opt_in: Mapped[bool] = mapped_column(server_default=text("false"))
    research_consent: Mapped[bool] = mapped_column(server_default=text("false"))
    research_consent_at: Mapped[dt.datetime | None]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        CheckConstraint(
            "profile_visibility IN ('private', 'friends', 'groups')",
            name="profile_visibility",
        ),
        CheckConstraint(
            "stats_visibility IN ('private', 'friends', 'groups')",
            name="stats_visibility",
        ),
        CheckConstraint(
            "(research_consent = false) OR (research_consent_at IS NOT NULL)",
            name="research_consent_timestamp",
        ),
    )
