"""Dishka wiring for the application layer (03_Technology_Decisions.md
ADR-005). Each use case is ``REQUEST``-scoped, built through an explicit
factory rather than Dishka's ``provide(SomeClass)`` auto-wiring shorthand —
that shorthand needs real (non-``TYPE_CHECKING``) imports on the use case's
``__init__`` to resolve its type hints at container-build time, which would
force every use case to know Dishka exists. An explicit factory here keeps
each use case a plain, hand-constructible class with zero framework
awareness of its own (ADR-005's mitigation: replacing Dishka means rewriting
this container, not the services).
"""

from __future__ import annotations

from dishka import Provider, Scope, provide

from ssa.application.identity.use_cases.link_telegram_account import LinkTelegramAccount
from ssa.application.identity.use_cases.register_user import RegisterUser
from ssa.application.identity.use_cases.update_privacy_settings import UpdatePrivacySettings
from ssa.application.tracking.use_cases.create_subject import CreateSubject
from ssa.domain.common.protocols import Clock, UnitOfWork
from ssa.domain.identity.repositories import (
    PrivacySettingsRepository,
    TelegramAccountRepository,
    UserRepository,
)
from ssa.domain.tracking.repositories import SubjectRepository

__all__ = ["ApplicationProvider"]


class ApplicationProvider(Provider):
    """One factory per use case — nothing else belongs here, so a missing
    use case fails container validation at startup rather than an
    ``AttributeError`` deep inside a handler."""

    @provide(scope=Scope.REQUEST)
    def get_register_user(
        self,
        users: UserRepository,
        privacy_settings: PrivacySettingsRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> RegisterUser:
        return RegisterUser(users=users, privacy_settings=privacy_settings, clock=clock, uow=uow)

    @provide(scope=Scope.REQUEST)
    def get_link_telegram_account(
        self,
        users: UserRepository,
        telegram_accounts: TelegramAccountRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> LinkTelegramAccount:
        return LinkTelegramAccount(
            users=users, telegram_accounts=telegram_accounts, clock=clock, uow=uow
        )

    @provide(scope=Scope.REQUEST)
    def get_update_privacy_settings(
        self,
        privacy_settings: PrivacySettingsRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> UpdatePrivacySettings:
        return UpdatePrivacySettings(privacy_settings=privacy_settings, clock=clock, uow=uow)

    @provide(scope=Scope.REQUEST)
    def get_create_subject(
        self,
        users: UserRepository,
        subjects: SubjectRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> CreateSubject:
        return CreateSubject(users=users, subjects=subjects, clock=clock, uow=uow)
