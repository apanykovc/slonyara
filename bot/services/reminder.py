"""Reminder service that periodically notifies users about upcoming meetings."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Set, Tuple

from zoneinfo import ZoneInfo

from aiogram import Bot

from bot.models.storage import Meeting, MeetingStorage

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ReminderJob:
    meeting: Meeting
    chat_id: int
    lead_time: int
    attempts: int = 0

    @property
    def identity(self) -> Tuple[str, int, int]:
        return (self.meeting.id, self.chat_id, self.lead_time)


class ReminderService:
    """Background service that polls storage for meetings requiring reminders."""

    def __init__(
        self,
        bot: Bot,
        storage: MeetingStorage,
        *,
        lead_times: Iterable[int],
        check_interval: int,
        timezone: ZoneInfo,
        max_attempts: int = 3,
        retry_delay: int = 5,
    ) -> None:
        self._bot = bot
        self._storage = storage
        self._lead_times: Tuple[int, ...] = tuple(sorted(set(int(max(0, lt)) for lt in lead_times))) or (0,)
        self._check_interval = check_interval
        self._timezone = timezone
        self._max_attempts = max(1, max_attempts)
        self._retry_delay = max(1, retry_delay)
        self._scheduler_task: Optional[asyncio.Task] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[_ReminderJob] = asyncio.Queue()
        self._pending: Set[Tuple[str, int, int]] = set()

    @property
    def timezone(self) -> ZoneInfo:
        """Return service timezone."""

        return self._timezone

    @property
    def default_lead_times(self) -> Tuple[int, ...]:
        """Configured default lead times."""

        return self._lead_times

    async def start(self) -> None:
        if self._scheduler_task is not None:
            return
        self._scheduler_task = asyncio.create_task(self._run_scheduler(), name="reminder-scheduler")
        self._worker_task = asyncio.create_task(self._run_worker(), name="reminder-worker")
        _logger.info("Reminder service started")

    async def stop(self) -> None:
        tasks = [task for task in (self._scheduler_task, self._worker_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._scheduler_task = None
        self._worker_task = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._pending.clear()
        _logger.info("Reminder service stopped")

    async def _run_scheduler(self) -> None:
        try:
            while True:
                await self.send_due_reminders()
                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            _logger.debug("Reminder scheduler cancelled")
            raise

    async def _run_worker(self) -> None:
        try:
            while True:
                job = await self._queue.get()
                success = False
                try:
                    success = await self._deliver(job)
                finally:
                    if success:
                        self._pending.discard(job.identity)
                    self._queue.task_done()
        except asyncio.CancelledError:
            _logger.debug("Reminder worker cancelled")
            raise

    async def send_due_reminders(self) -> None:
        now = datetime.now(tz=self._timezone)
        for job in self._collect_due_jobs(now):
            await self._enqueue(job)

    async def _enqueue(self, job: _ReminderJob, *, force: bool = False) -> None:
        if not force and job.identity in self._pending:
            return
        self._pending.add(job.identity)
        await self._queue.put(job)

    def _collect_due_jobs(self, now: datetime) -> Iterable[_ReminderJob]:
        meetings = self._storage.list_meetings()
        for meeting in meetings:
            if meeting.chat_id is None:
                continue
            chat = self._storage.get_chat(meeting.chat_id)
            if not chat:
                continue
            lead_times = tuple(chat.lead_times) if chat.lead_times else self._lead_times
            for lead_time in lead_times:
                if self._storage.is_reminder_sent(meeting.id, meeting.chat_id, lead_time):
                    continue
                due_at = meeting.scheduled_at - timedelta(seconds=lead_time)
                if due_at > now:
                    continue
                yield _ReminderJob(meeting=meeting, chat_id=meeting.chat_id, lead_time=lead_time)

    async def _deliver(self, job: _ReminderJob) -> bool:
        message = self._render_message(job.meeting, job.lead_time)
        try:
            await self._bot.send_message(job.chat_id, message)
        except Exception:  # pragma: no cover - networking errors are logged
            job.attempts += 1
            if job.attempts >= self._max_attempts:
                _logger.exception(
                    "Failed to send reminder for meeting %s in chat %s after %s attempts",
                    job.meeting.id,
                    job.chat_id,
                    job.attempts,
                )
                return True
            _logger.warning(
                "Retrying reminder for meeting %s in chat %s (%s/%s)",
                job.meeting.id,
                job.chat_id,
                job.attempts,
                self._max_attempts,
            )
            await asyncio.sleep(self._retry_delay)
            await self._enqueue(job, force=True)
            return False

        self._storage.mark_reminder_sent(job.meeting.id, job.chat_id, job.lead_time)
        _logger.info(
            "Reminder sent for meeting %s (chat=%s, lead_time=%ss)",
            job.meeting.id,
            job.chat_id,
            job.lead_time,
        )
        return True

    @staticmethod
    def _render_message(meeting: Meeting, lead_time: int) -> str:
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
        if lead_time > 0:
            lines.append(f"До начала осталось {ReminderService._format_lead_time(lead_time)}")
        else:
            lines.append("Встреча начинается прямо сейчас!")
        lines.append(f"Когда: {scheduled_at}")
        if meeting.request_number:
            lines.append(f"Заявка: {meeting.request_number}")
        if meeting.participants:
            participants = ", ".join(str(pid) for pid in meeting.participants)
            lines.append(f"Участники: {participants}")
        return "\n".join(lines)

    @staticmethod
    def _format_lead_time(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} сек."
        minutes, remainder = divmod(seconds, 60)
        if minutes < 60:
            if remainder:
                return f"{minutes} мин {remainder} сек."
            return f"{minutes} мин"
        hours, minutes = divmod(minutes, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} ч")
        if minutes:
            parts.append(f"{minutes} мин")
        if remainder:
            parts.append(f"{remainder} сек.")
        return " ".join(parts) if parts else f"{seconds} сек."
