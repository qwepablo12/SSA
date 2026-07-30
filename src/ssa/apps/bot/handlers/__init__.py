"""Feature handler routers, aggregated into one root router.

One module per feature (02_Project_Structure.md §5). A handler module must
contain no business logic — it replies, it does not decide.
"""

from __future__ import annotations

from aiogram import Router

from ssa.apps.bot.handlers.start import router as start_router
from ssa.apps.bot.handlers.study import router as study_router
from ssa.apps.bot.handlers.subject import router as subject_router

__all__ = ["router"]

router = Router(name="root")
router.include_router(start_router)
router.include_router(subject_router)
router.include_router(study_router)
