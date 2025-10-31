"""Simple bot facade that ensures the scheduler is running."""

from __future__ import annotations

import logging

from .scheduler import ensure_scheduler_started
from .reminders.service import MessageSender, ReminderService

_logger = logging.getLogger(__name__)


class ConsoleMessageSender(MessageSender):
    """Fallback message sender that prints messages to stdout."""

    async def send_message(self, chat_id: int, text: str) -> None:
        _logger.info("Sending message to chat %s: %s", chat_id, text)
        print(f"[{chat_id}] {text}")


class ReminderBot:
    """High level entry point used to run the bot."""

    def __init__(
        self,
        *,
        message_sender: MessageSender | None = None,
    ) -> None:
        self.message_sender = message_sender or ConsoleMessageSender()
        self.reminders = ReminderService(message_sender=self.message_sender)

    async def start(self) -> None:
        """Initialise the bot and start the scheduler."""

        ensure_scheduler_started()
        _logger.info("Bot initialised. Scheduler is running")

    async def create_meeting(self, meeting) -> None:
        """Schedule reminders after a meeting has been created."""

        self.reminders.schedule_for_meeting(meeting)

    async def update_meeting(self, meeting) -> None:
        """Re-schedule reminders when a meeting has changed."""

        self.reminders.reschedule_for_meeting(meeting)

    async def shutdown(self) -> None:
        _logger.info("Bot shutdown requested")
        # In a real application we would stop the scheduler and bot here.
