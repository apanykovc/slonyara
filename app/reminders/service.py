"""Reminder scheduling service built on top of APScheduler."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Sequence

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..scheduler import get_scheduler
from .models import Meeting, Reminder, create_reminder
from .repository import ReminderRepository

_logger = logging.getLogger(__name__)


class ReminderService:
    """High level API for scheduling meeting reminders."""

    def __init__(
        self,
        repository: ReminderRepository | None = None,
        scheduler: AsyncIOScheduler | None = None,
        *,
        message_sender: "MessageSender",
    ) -> None:
        self.repository = repository or ReminderRepository()
        self.scheduler = scheduler or get_scheduler()
        self.message_sender = message_sender

    # public API -------------------------------------------------------
    def schedule_for_meeting(self, meeting: Meeting) -> Sequence[Reminder]:
        """Schedule reminders for a newly created meeting."""

        _logger.debug("Scheduling reminders for meeting %s", meeting.id)
        # Clear previously scheduled reminders just in case this method is
        # accidentally called twice for the same meeting.
        self._cancel_meeting_jobs(meeting.id)
        reminders = list(self._schedule_reminders(meeting))
        _logger.info("Scheduled %d reminders for meeting %s", len(reminders), meeting.id)
        return reminders

    def reschedule_for_meeting(self, meeting: Meeting) -> Sequence[Reminder]:
        """Recreate reminders for an updated meeting."""

        _logger.debug("Rescheduling reminders for meeting %s", meeting.id)
        self._cancel_meeting_jobs(meeting.id)
        reminders = list(self._schedule_reminders(meeting))
        _logger.info("Rescheduled %d reminders for meeting %s", len(reminders), meeting.id)
        return reminders

    # internal helpers -------------------------------------------------
    def _schedule_reminders(self, meeting: Meeting) -> Iterable[Reminder]:
        now = datetime.now(tz=meeting.start_at.tzinfo)
        for reminder_id, send_at in meeting.iter_absolute_reminders(now=now):
            reminder = create_reminder(
                meeting,
                reminder_id=reminder_id,
                send_at=send_at,
                message=self._build_message(meeting),
            )
            self.repository.upsert(reminder)
            self._add_job(reminder)
            yield reminder

    def _cancel_meeting_jobs(self, meeting_id: str) -> None:
        for reminder in self.repository.delete_meeting(meeting_id):
            job_id = self._job_id(reminder.meeting_id, reminder.id)
            job = self.scheduler.get_job(job_id)
            if job:
                job.remove()

    # job helpers ------------------------------------------------------
    def _add_job(self, reminder: Reminder) -> None:
        job_id = self._job_id(reminder.meeting_id, reminder.id)
        _logger.debug("Registering reminder job %s for %s", job_id, reminder.send_at)
        self.scheduler.add_job(
            self._send_reminder,
            trigger="date",
            id=job_id,
            run_date=reminder.send_at,
            kwargs={
                "meeting_id": reminder.meeting_id,
                "reminder_id": reminder.id,
            },
            replace_existing=True,
        )

    async def _send_reminder(self, *, meeting_id: str, reminder_id: str) -> None:
        """Callback executed by APScheduler when the reminder should be sent."""

        reminder = self.repository.get(meeting_id, reminder_id)
        if reminder is None:
            _logger.warning("Reminder %s for meeting %s disappeared before sending", reminder_id, meeting_id)
            return
        if reminder.sent_at is not None:
            _logger.info("Reminder %s for meeting %s already sent at %s", reminder_id, meeting_id, reminder.sent_at)
            return

        _logger.info("Sending reminder %s for meeting %s", reminder_id, meeting_id)
        await self.message_sender.send_message(reminder.chat_id, reminder.message)
        sent_at = datetime.now(tz=reminder.send_at.tzinfo)
        self.repository.mark_sent(meeting_id, reminder_id, sent_at)
        _logger.debug("Reminder %s marked as sent at %s", reminder_id, sent_at.isoformat())

    @staticmethod
    def _job_id(meeting_id: str, reminder_id: str) -> str:
        return f"meeting:{meeting_id}:reminder:{reminder_id}"

    @staticmethod
    def _build_message(meeting: Meeting) -> str:
        return (
            f"Напоминание: встреча '{meeting.title}' начнется в {meeting.start_at:%H:%M}"
            f" ({meeting.start_at:%d.%m.%Y})."
        )


class MessageSender:
    """Abstraction over the actual bot instance used for messaging."""

    async def send_message(self, chat_id: int, text: str) -> None:  # pragma: no cover - interface method
        raise NotImplementedError
