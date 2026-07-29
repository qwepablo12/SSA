"""``UpdatePrivacySettings`` — change a user's privacy and consent state
(06_Database_Schema.md §4). This is the sole write path onto
``research_consent``, so it goes through the entity's own
``grant_research_consent``/``revoke_research_consent`` to keep the consent
timestamp invariant (``research_consent`` implies ``research_consent_at``)
enforced in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ssa.application.common.decorators import transactional
from ssa.application.identity.dto import UpdatePrivacySettingsResult

if TYPE_CHECKING:
    from ssa.application.identity.dto import UpdatePrivacySettingsRequest
    from ssa.domain.common.protocols import Clock, UnitOfWork
    from ssa.domain.identity.repositories import PrivacySettingsRepository

__all__ = ["UpdatePrivacySettings"]


class UpdatePrivacySettings:
    """Every field on the request is optional; a field left ``None`` is left
    unchanged, so a caller can flip a single setting without re-sending the
    rest. Fails with :class:`~ssa.domain.common.errors.NotFoundError` if the
    user has no privacy settings row — which should never happen post-
    :class:`~ssa.application.identity.use_cases.register_user.RegisterUser`,
    but is a real condition worth a clean error rather than an assertion."""

    def __init__(
        self,
        *,
        privacy_settings: PrivacySettingsRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._privacy_settings = privacy_settings
        self._clock = clock
        self._uow = uow

    @transactional
    async def execute(self, request: UpdatePrivacySettingsRequest) -> UpdatePrivacySettingsResult:
        settings = await self._privacy_settings.get_by_user_id(request.user_id)

        if request.profile_visibility is not None:
            settings.profile_visibility = request.profile_visibility
        if request.stats_visibility is not None:
            settings.stats_visibility = request.stats_visibility
        if request.leaderboard_opt_in is not None:
            settings.leaderboard_opt_in = request.leaderboard_opt_in
        if request.research_consent is True:
            settings.grant_research_consent(at=self._clock.now())
        elif request.research_consent is False:
            settings.revoke_research_consent()

        await self._privacy_settings.update(settings)

        return UpdatePrivacySettingsResult(
            user_id=settings.user_id,
            profile_visibility=settings.profile_visibility,
            stats_visibility=settings.stats_visibility,
            leaderboard_opt_in=settings.leaderboard_opt_in,
            research_consent=settings.research_consent,
            research_consent_at=settings.research_consent_at,
        )
