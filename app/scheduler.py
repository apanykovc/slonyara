"""Utilities for working with the global APScheduler instance."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

_logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Return a lazily instantiated :class:`AsyncIOScheduler`.

    The project uses a single scheduler shared across the whole application so
    that we can easily register or cancel jobs from any module.  The scheduler is
    created on demand to make unit testing easier (tests can create an event loop
    before instantiating the scheduler).
    """

    global _scheduler
    if _scheduler is None:
        _logger.debug("Creating global AsyncIOScheduler instance")
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def ensure_scheduler_started() -> AsyncIOScheduler:
    """Start the scheduler if it has not been started yet.

    The function is idempotent: calling it multiple times is safe because
    ``AsyncIOScheduler.start`` simply does nothing if the scheduler is already
    running.
    """

    scheduler = get_scheduler()
    if not scheduler.running:
        _logger.info("Starting APScheduler")
        scheduler.start()
    return scheduler


def shutdown_scheduler(wait: bool = True) -> None:
    """Shutdown the shared scheduler if it is running."""

    scheduler = get_scheduler()
    if scheduler.running:
        _logger.info("Shutting down APScheduler")
        scheduler.shutdown(wait=wait)
