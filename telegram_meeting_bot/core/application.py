from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from ..config import Config
from ..jobs.scheduler import Scheduler
from ..logging_config import setup_logging
from ..services.chats import ChatService
from ..services.events import EventsService
from ..services.reminders import ReminderService
from ..services.users import UserService
from ..services.telegram import TelegramSender
from ..utils.locks import ClickGuard
from ..utils.metrics import MetricsCollector
from .middlewares.callback_guard import CallbackGuardMiddleware
from .middlewares.context import ContextMiddleware
from .dispatcher import create_dispatcher

logger = logging.getLogger("telegram_meeting_bot.core.application")


class Application:
    def __init__(self, *, config: Config) -> None:
        self._config = config
        setup_logging(config.bot.logs_dir)
        config.bot.data_dir.mkdir(parents=True, exist_ok=True)
        config.bot.logs_dir.mkdir(parents=True, exist_ok=True)

        self._bot = Bot(token=config.bot.token, default=DefaultBotProperties(parse_mode="HTML"))
        self._events = EventsService(config.bot)
        self._users = UserService(config.bot)
        self._chats = ChatService(config.bot)
        self._metrics = MetricsCollector()
        self._sender = TelegramSender(bot=self._bot, network=config.network, metrics=self._metrics)
        self._reminders = ReminderService(
            events=self._events,
            chats=self._chats,
            users=self._users,
            metrics=self._metrics,
            bot_config=config.bot,
            sender=self._sender,
        )
        self._scheduler = Scheduler(
            bot_config=config.bot,
            reminder_service=self._reminders,
            telegram_sender=self._sender,
            metrics=self._metrics,
        )
        self._guard = ClickGuard()
        self._dispatcher = create_dispatcher()
        context_services = dict(
            events=self._events,
            users=self._users,
            chats=self._chats,
            config=config,
            metrics=self._metrics,
            telegram_sender=self._sender,
        )
        self._dispatcher.message.middleware.register(ContextMiddleware(**context_services))
        self._dispatcher.callback_query.middleware.register(
            CallbackGuardMiddleware(self._guard, self._sender)
        )
        self._dispatcher.callback_query.middleware.register(ContextMiddleware(**context_services))

    async def run(self) -> None:
        await self._scheduler.start()
        try:
            await self._dispatcher.start_polling(self._bot)
        finally:
            with suppress(Exception):
                await self._scheduler.shutdown()
            await self._bot.session.close()
