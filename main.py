"""Entrypoint for running the reminder bot manually."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.bot import ReminderBot
from app.reminders.models import create_meeting

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    bot = ReminderBot()
    await bot.start()

    meeting = create_meeting(
        chat_id=123,
        title="Созвон с командой",
        start_at=datetime.now() + timedelta(minutes=5),
        reminder_offsets=[timedelta(minutes=1), timedelta(minutes=3)],
    )
    await bot.create_meeting(meeting)

    # Keep the script alive so the scheduler can fire.
    await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
