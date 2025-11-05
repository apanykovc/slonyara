"""Application bootstrap helpers."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.config import load_config
from bot.handlers import admin as admin_handlers
from bot.handlers import user as user_handlers
from bot.infra import (
    SenderAiohttpSession,
    SenderContextMiddleware,
    TelegramSender,
    TelegramSenderConfig,
)
from bot.models.storage import MeetingStorage
from bot.services.reminder import ReminderService, TimeoutProfile

_logger = logging.getLogger(__name__)


def _create_sender(config) -> TelegramSender:
    return TelegramSender(
        ui=TelegramSenderConfig(
            timeout=config.reminder.timeouts.ui,
            max_attempts=2,
            rps=20.0,
            retry_base_delay=0.25,
            retry_multiplier=1.5,
            retry_max_delay=2.0,
        ),
        background=TelegramSenderConfig(
            timeout=config.reminder.timeouts.background,
            max_attempts=config.reminder.retry.attempts,
            rps=8.0,
            retry_base_delay=config.reminder.retry.delay,
            retry_multiplier=2.0,
            retry_max_delay=config.reminder.retry.max_delay,
        ),
    )


@asynccontextmanager
async def build_runtime():
    load_dotenv()
    config = load_config()
    sender = _create_sender(config)
    session = SenderAiohttpSession(sender)
    bot = Bot(token=config.bot.token, parse_mode=getattr(ParseMode, config.bot.parse_mode.upper(), ParseMode.HTML), session=session)
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware.register(SenderContextMiddleware(sender))
    storage = create_storage(config)
    reminder = ReminderService(
        bot=bot,
        sender=sender,
        storage=storage,
        lead_times=config.reminder.lead_times,
        check_interval=config.reminder.check_interval,
        timezone=config.timezone,
        max_attempts=config.reminder.retry.attempts,
        retry_delay=config.reminder.retry.delay,
        max_retry_delay=config.reminder.retry.max_delay,
        retry_jitter=config.reminder.retry.jitter,
        timeout_profile=TimeoutProfile(
            ui=config.reminder.timeouts.ui,
            background=config.reminder.timeouts.background,
        ),
    )

    dispatcher.startup.register(sender.start)
    dispatcher.startup.register(reminder.start)
    dispatcher.shutdown.register(reminder.stop)
    dispatcher.shutdown.register(sender.stop)

    user_handlers.register(dispatcher, storage, reminder)
    admin_handlers.register(
        dispatcher,
        storage,
        reminder,
        config.bot.admins,
        config.bot.admin_usernames,
        config.reminder.lead_times,
    )

    try:
        yield config, dispatcher, bot, storage
    finally:
        storage.close()
        await session.close()


def create_storage(config) -> MeetingStorage:
    """Construct a :class:`MeetingStorage` instance from configuration."""

    return MeetingStorage(
        config.storage_path,
        timezone=config.timezone,
        default_lead_times=config.reminder.lead_times,
        default_user_lead_time=config.reminder.default_lead_time,
        default_locale=config.locale,
    )


async def run_bot() -> None:
    async with build_runtime() as (config, dispatcher, bot, _storage):
        _logger.info("Starting bot with database at %s", config.storage_path)
        await dispatcher.start_polling(bot)
        _logger.info("Bot stopped")
