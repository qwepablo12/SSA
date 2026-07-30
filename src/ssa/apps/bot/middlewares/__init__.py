"""Aiogram middlewares: correlation id, user resolution, throttling, error
translation (02_Project_Structure.md §5).

DI is already wired — via Dishka's own ``ContainerMiddleware``, registered by
``setup_dishka()`` in ``apps/bot/main.py`` rather than a module here. The
remaining middlewares are not yet implemented.
"""
