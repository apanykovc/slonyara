from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import BotConfig
from ..services.reminders import ReminderService
from ..services.telegram import TelegramSender
from ..utils.metrics import MetricsCollector

logger = logging.getLogger("telegram_meeting_bot.jobs.scheduler")


class Scheduler:
    def __init__(
        self,
        *,
        bot_config: BotConfig,
        reminder_service: ReminderService,
        telegram_sender: TelegramSender,
        metrics: MetricsCollector,
    ) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC", coalesce=True, misfire_grace_time=30)
        self._reminder_service = reminder_service
        self._sender = telegram_sender
        self._metrics = metrics
        self._bot_config = bot_config

    async def start(self) -> None:
        self._scheduler.add_job(
            self._reminder_job,
            "interval",
            seconds=self._bot_config.scheduler_tick_seconds,
            max_instances=3,
        )
        self._scheduler.add_job(self._sender.worker_tick, "interval", seconds=0.3, max_instances=3, coalesce=True, misfire_grace_time=30)
        self._scheduler.add_job(self._metrics_job, "interval", minutes=5, max_instances=1, coalesce=True)
        self._scheduler.add_job(self._digest_job, "interval", minutes=5, max_instances=1, coalesce=True)
        self._scheduler.start()
        logger.info("scheduler started")

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def _reminder_job(self) -> None:
        await self._reminder_service.dispatch_due_events()

    async def _metrics_job(self) -> None:
        await self._metrics.log_summary()

    async def _digest_job(self) -> None:
        await self._reminder_service.dispatch_daily_digest()
