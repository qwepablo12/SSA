"""Telegram bot entrypoint (aiogram 3).

Long-polling skeleton with no business logic yet — ``Bot``, ``Dispatcher``,
and routers wired up per 02_Project_Structure.md §9 step 7. Use cases land in
handlers in a later step.

Handlers must never import ``ssa.infrastructure.database.models`` or
``matplotlib`` — enforced by import-linter (pyproject.toml).
"""
