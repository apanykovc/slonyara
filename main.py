"""Entry point for the Telegram meeting reminder bot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.config import load_config
from bot.handlers import admin as admin_handlers
from bot.handlers import user as user_handlers
from bot.models.storage import MeetingStorage
from bot.services.reminder import ReminderService


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    load_dotenv()

    config = load_config()
    parse_mode = getattr(ParseMode, config.bot.parse_mode.upper(), ParseMode.HTML)
    bot = Bot(token=config.bot.token, parse_mode=parse_mode)
    dispatcher = Dispatcher()

    storage = MeetingStorage(
        config.storage_path,
        timezone=config.timezone,
        default_lead_times=config.reminder.lead_times,
    )
    reminder = ReminderService(
        bot=bot,
        storage=storage,
        lead_times=config.reminder.lead_times,
        check_interval=config.reminder.check_interval,
        timezone=config.timezone,
    )

    dispatcher.startup.register(reminder.start)
    dispatcher.shutdown.register(reminder.stop)

    user_handlers.register(dispatcher, storage)
    admin_handlers.register(
        dispatcher,
        storage,
        reminder,
        config.bot.admins,
        config.bot.admin_usernames,
        config.reminder.lead_times,
    )

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
