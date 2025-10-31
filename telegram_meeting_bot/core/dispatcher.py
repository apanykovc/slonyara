from __future__ import annotations

from aiogram import Dispatcher

from ..routers import admin, events, settings, start


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(events.router)
    dp.include_router(settings.router)
    dp.include_router(admin.router)
    return dp
