"""ORM model ⇄ domain entity mappers for the identity module (ADR-004).

Kept separate from the repositories so the field-by-field translation is
reviewable on its own, rather than interleaved with query code. Three
functions per entity:

* ``*_to_domain`` — read path, ORM row to domain entity.
* ``new_*_model`` — write path for a brand-new row (entity's surrogate id,
  if any, must still be ``None``).
* ``update_*_model`` — write path for an existing row: copies the entity's
  mutable fields onto an already-tracked ORM instance so the session's own
  change tracking picks them up.
"""

from __future__ import annotations

from ssa.domain.identity.entities import PrivacySettings, TelegramAccount, User
from ssa.domain.identity.enums import UserStatus, Visibility
from ssa.infrastructure.database import models

__all__ = [
    "new_privacy_settings_model",
    "new_telegram_account_model",
    "new_user_model",
    "privacy_settings_to_domain",
    "telegram_account_to_domain",
    "update_privacy_settings_model",
    "update_telegram_account_model",
    "update_user_model",
    "user_to_domain",
]


def user_to_domain(model: models.User) -> User:
    return User(
        id=model.id,
        public_id=model.public_id,
        timezone=model.timezone,
        locale=model.locale,
        status=UserStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        display_name=model.display_name,
        onboarding_completed_at=model.onboarding_completed_at,
        deleted_at=model.deleted_at,
    )


def new_user_model(user: User) -> models.User:
    return models.User(
        public_id=user.public_id,
        timezone=user.timezone,
        locale=user.locale,
        display_name=user.display_name,
        status=user.status.value,
        onboarding_completed_at=user.onboarding_completed_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
        deleted_at=user.deleted_at,
    )


def update_user_model(user: User, model: models.User) -> None:
    """``updated_at`` is deliberately not copied: it is ``onupdate=func.now()``
    server-side (``types.py``), and setting it explicitly here would suppress
    that trigger for this statement."""
    model.timezone = user.timezone
    model.locale = user.locale
    model.display_name = user.display_name
    model.status = user.status.value
    model.onboarding_completed_at = user.onboarding_completed_at
    model.deleted_at = user.deleted_at


def telegram_account_to_domain(model: models.TelegramAccount) -> TelegramAccount:
    return TelegramAccount(
        user_id=model.user_id,
        telegram_id=model.telegram_id,
        chat_id=model.chat_id,
        linked_at=model.linked_at,
        telegram_username=model.telegram_username,
        language_code=model.language_code,
        last_seen_at=model.last_seen_at,
    )


def new_telegram_account_model(account: TelegramAccount) -> models.TelegramAccount:
    return models.TelegramAccount(
        user_id=account.user_id,
        telegram_id=account.telegram_id,
        chat_id=account.chat_id,
        telegram_username=account.telegram_username,
        language_code=account.language_code,
        linked_at=account.linked_at,
        last_seen_at=account.last_seen_at,
    )


def update_telegram_account_model(account: TelegramAccount, model: models.TelegramAccount) -> None:
    model.chat_id = account.chat_id
    model.telegram_username = account.telegram_username
    model.language_code = account.language_code
    model.last_seen_at = account.last_seen_at


def privacy_settings_to_domain(model: models.PrivacySettings) -> PrivacySettings:
    return PrivacySettings(
        user_id=model.user_id,
        updated_at=model.updated_at,
        profile_visibility=Visibility(model.profile_visibility),
        stats_visibility=Visibility(model.stats_visibility),
        leaderboard_opt_in=model.leaderboard_opt_in,
        research_consent=model.research_consent,
        research_consent_at=model.research_consent_at,
    )


def new_privacy_settings_model(settings: PrivacySettings) -> models.PrivacySettings:
    return models.PrivacySettings(
        user_id=settings.user_id,
        profile_visibility=settings.profile_visibility.value,
        stats_visibility=settings.stats_visibility.value,
        leaderboard_opt_in=settings.leaderboard_opt_in,
        research_consent=settings.research_consent,
        research_consent_at=settings.research_consent_at,
        updated_at=settings.updated_at,
    )


def update_privacy_settings_model(settings: PrivacySettings, model: models.PrivacySettings) -> None:
    model.profile_visibility = settings.profile_visibility.value
    model.stats_visibility = settings.stats_visibility.value
    model.leaderboard_opt_in = settings.leaderboard_opt_in
    model.research_consent = settings.research_consent
    model.research_consent_at = settings.research_consent_at
