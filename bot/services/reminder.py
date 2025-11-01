"""Reminder service that periodically notifies users about upcoming meetings."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from zoneinfo import ZoneInfo

from aiogram import Bot

from bot.models.storage import Meeting, MeetingStorage

_logger = logging.getLogger(__name__)


class ReminderService:
    """Background service that polls storage for meetings requiring reminders."""

    def __init__(
        self,
        bot: Bot,
        storage: MeetingStorage,
        *,
        lead_time: int,
        check_interval: int,
        timezone: ZoneInfo,
    ) -> None:
        self._bot = bot
        self._storage = storage
        self._lead_time = lead_time
        self._check_interval = check_interval
        self._timezone = timezone
        self._task: Optional[asyncio.Task] = None

    @property
    def timezone(self) -> ZoneInfo:
        """Return service timezone."""

        return self._timezone

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="reminder-service")
            _logger.info("Reminder service started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        _logger.info("Reminder service stopped")

    async def _run(self) -> None:
        try:
            while True:
                await self.send_due_reminders()
                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            _logger.debug("Reminder service cancelled")
            raise

    async def send_due_reminders(self) -> None:
        now = datetime.now(tz=self._timezone)
        meetings = self._storage.get_due_meetings(now, self._lead_time)
        for meeting in meetings:
            await self._notify_meeting(meeting)
            self._storage.mark_reminder_sent(meeting.id)

    async def _notify_meeting(self, meeting: Meeting) -> None:
        message = self._render_message(meeting)
        for participant_id in meeting.participants:
            try:
                await self._bot.send_message(participant_id, message)
            except Exception:  # pragma: no cover - networking errors are logged
                _logger.exception("Failed to send reminder for meeting %s", meeting.id)

    @staticmethod
    def _render_message(meeting: Meeting) -> str:
        scheduled_at = meeting.scheduled_at.strftime("%d.%m.%Y %H:%M")
        title_parts = []
        if meeting.meeting_type:
            title_parts.append(meeting.meeting_type)
        elif meeting.title:
            title_parts.append(meeting.title)
        if meeting.room:
            title_parts.append(f"Переговорная {meeting.room}")
        header = " · ".join(title_parts) if title_parts else meeting.title or "Встреча"
        lines = [f"⏰ Напоминание о встрече \"{header}\""]
        lines.append(f"Когда: {scheduled_at}")
        if meeting.request_number:
            lines.append(f"Заявка: {meeting.request_number}")
        participants = ", ".join(str(pid) for pid in meeting.participants)
        lines.append(f"Участники: {participants}")
        return "\n".join(lines)
