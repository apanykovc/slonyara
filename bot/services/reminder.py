"""Reminder service that schedules chat notifications about upcoming meetings."""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Set, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

from aiogram import Bot

from bot.models.storage import ChatSettings, Meeting, MeetingStorage

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TimeoutProfile:
    """Timeout presets for bot API requests."""

    ui: float = 5.0
    background: float = 15.0


@dataclass(slots=True)
class _ReminderJob:
    meeting_id: str
    chat_id: int
    lead_time: int
    attempts: int = 0

    @property
    def identity(self) -> Tuple[str, int, int]:
        return (self.meeting_id, self.chat_id, self.lead_time)


class ReminderService:
    """Background service that uses APScheduler to send group chat reminders."""

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
        max_retry_delay: int = 60,
        retry_jitter: float = 0.3,
        timeout_profile: TimeoutProfile | None = None,
    ) -> None:
        self._bot = bot
        self._storage = storage
        self._lead_times: Tuple[int, ...] = tuple(sorted(set(int(max(0, lt)) for lt in lead_times))) or (0,)
        self._check_interval = check_interval
        self._timezone = timezone
        self._max_attempts = max(1, max_attempts)
        self._retry_delay = max(1, retry_delay)
        self._max_retry_delay = max(self._retry_delay, max_retry_delay)
        self._retry_jitter = max(0.0, retry_jitter)
        self._timeout_profile = timeout_profile or TimeoutProfile()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[_ReminderJob] = asyncio.Queue()
        self._pending: Set[Tuple[str, int, int]] = set()
        self._refresh_lock = asyncio.Lock()

    @property
    def timezone(self) -> ZoneInfo:
        """Return service timezone."""

        return self._timezone

    @property
    def default_lead_times(self) -> Tuple[int, ...]:
        """Configured default lead times."""

        return self._lead_times

    async def start(self) -> None:
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler(timezone=self._timezone)
            self._scheduler.start()
        elif not self._scheduler.running:
            self._scheduler.start()
        if self._check_interval > 0 and self._scheduler.get_job("reminder-refresh") is None:
            self._scheduler.add_job(
                self.refresh_schedule,
                trigger="interval",
                seconds=self._check_interval,
                id="reminder-refresh",
                replace_existing=True,
            )
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run_worker(), name="reminder-worker")
        await self.refresh_schedule()
        _logger.info("Reminder service started")

    async def stop(self) -> None:
        tasks = [task for task in (self._worker_task,) if task is not None]
        for task in tasks:
            task.cancel()
        if self._scheduler is not None:
            await self._scheduler.shutdown(wait=False)
            self._scheduler = None
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._pending.clear()
        _logger.info("Reminder service stopped")

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

    async def refresh_schedule(self) -> None:
        """Rebuild scheduler jobs and enqueue reminders that are already due."""

        async with self._refresh_lock:
            now = datetime.now(tz=self._timezone)
            active_jobs: Set[str] = set()
            for meeting in self._storage.list_meetings():
                if meeting.chat_id is None:
                    continue
                chat = self._storage.get_chat(meeting.chat_id)
                if not chat:
                    continue
                lead_times = self._resolve_lead_times(meeting, chat)
                if not lead_times:
                    self._remove_all_jobs_for_meeting(meeting.id, meeting.chat_id)
                    continue
                for lead_time in lead_times:
                    job_id = self._job_id(meeting.id, meeting.chat_id, lead_time)
                    if self._storage.is_reminder_sent(meeting.id, meeting.chat_id, lead_time):
                        self._remove_scheduler_job(job_id)
                        continue
                    due_at = meeting.scheduled_at - timedelta(seconds=lead_time)
                    if due_at <= now:
                        await self._enqueue(
                            _ReminderJob(meeting_id=meeting.id, chat_id=meeting.chat_id, lead_time=lead_time)
                        )
                        self._remove_scheduler_job(job_id)
                    else:
                        self._schedule_future_job(meeting, meeting.chat_id, lead_time, due_at)
                        active_jobs.add(job_id)
            self._cleanup_scheduler_jobs(active_jobs)

    async def send_due_reminders(self) -> None:
        await self.refresh_schedule()

    async def _enqueue(self, job: _ReminderJob, *, force: bool = False) -> None:
        if not force and job.identity in self._pending:
            return
        self._pending.add(job.identity)
        await self._queue.put(job)

    async def _deliver(self, job: _ReminderJob) -> bool:
        meeting = self._storage.get_meeting(job.meeting_id)
        if not meeting or meeting.chat_id != job.chat_id:
            _logger.info(
                "Skipping reminder for missing meeting %s in chat %s", job.meeting_id, job.chat_id
            )
            return True
        if self._storage.is_reminder_sent(meeting.id, job.chat_id, job.lead_time):
            return True
        due_at = meeting.scheduled_at - timedelta(seconds=job.lead_time)
        now = datetime.now(tz=self._timezone)
        if due_at > now:
            self._schedule_future_job(meeting, job.chat_id, job.lead_time, due_at)
            return True
        message = self._render_message(meeting, job.lead_time)
        try:
            await self._bot.send_message(
                job.chat_id,
                message,
                timeout=self._timeout_profile.background,
            )
        except Exception:  # pragma: no cover - networking errors are logged
            job.attempts += 1
            if job.attempts >= self._max_attempts:
                _logger.exception(
                    "Failed to send reminder for meeting %s in chat %s after %s attempts",
                    job.meeting_id,
                    job.chat_id,
                    job.attempts,
                )
                return True
            _logger.warning(
                "Retrying reminder for meeting %s in chat %s (%s/%s)",
                job.meeting_id,
                job.chat_id,
                job.attempts,
                self._max_attempts,
            )
            delay = self._compute_retry_delay(job.attempts)
            await asyncio.sleep(delay)
            await self._enqueue(job, force=True)
            return False

        self._storage.mark_reminder_sent(meeting.id, job.chat_id, job.lead_time)
        _logger.info(
            "Reminder sent for meeting %s (chat=%s, lead_time=%ss)",
            job.meeting_id,
            job.chat_id,
            job.lead_time,
        )
        return True

    def _schedule_future_job(
        self, meeting: Meeting, chat_id: int, lead_time: int, run_at: datetime
    ) -> None:
        if self._scheduler is None:
            return
        job_id = self._job_id(meeting.id, chat_id, lead_time)
        self._scheduler.add_job(
            self._handle_scheduled_job,
            trigger="date",
            run_date=run_at,
            id=job_id,
            replace_existing=True,
            kwargs={
                "meeting_id": meeting.id,
                "chat_id": chat_id,
                "lead_time": lead_time,
            },
        )

    async def _handle_scheduled_job(self, meeting_id: str, chat_id: int, lead_time: int) -> None:
        meeting = self._storage.get_meeting(meeting_id)
        if not meeting or meeting.chat_id != chat_id:
            return
        chat = self._storage.get_chat(chat_id)
        if not chat:
            return
        if lead_time not in self._resolve_lead_times(meeting, chat):
            return
        if self._storage.is_reminder_sent(meeting_id, chat_id, lead_time):
            return
        await self._enqueue(_ReminderJob(meeting_id=meeting_id, chat_id=chat_id, lead_time=lead_time))

    def _resolve_lead_times(self, meeting: Meeting, chat: ChatSettings) -> Tuple[int, ...]:
        organizer_settings = self._storage.get_user_settings(meeting.organizer_id)
        user_lead = organizer_settings.default_lead_time
        if user_lead == 0:
            return tuple()
        if user_lead > 0:
            return (user_lead,)
        if chat.lead_times:
            return tuple(chat.lead_times)
        return self._lead_times

    def _cleanup_scheduler_jobs(self, keep: Set[str]) -> None:
        if self._scheduler is None:
            return
        for job in list(self._scheduler.get_jobs()):
            if job.id not in keep:
                job.remove()

    def _remove_scheduler_job(self, job_id: str) -> None:
        if self._scheduler is None:
            return
        job = self._scheduler.get_job(job_id)
        if job is not None:
            job.remove()

    def _remove_all_jobs_for_meeting(self, meeting_id: str, chat_id: int) -> None:
        if self._scheduler is None:
            return
        prefix = f"{meeting_id}:{chat_id}:"
        for job in list(self._scheduler.get_jobs()):
            if job.id and job.id.startswith(prefix):
                job.remove()

    def _job_id(self, meeting_id: str, chat_id: int, lead_time: int) -> str:
        return f"{meeting_id}:{chat_id}:{lead_time}"

    def _compute_retry_delay(self, attempts: int) -> float:
        base_delay = self._retry_delay * (2 ** max(0, attempts - 1))
        capped = min(base_delay, self._max_retry_delay)
        jitter = 0.0
        if self._retry_jitter > 0:
            jitter = random.uniform(0, capped * self._retry_jitter)
        return capped + jitter

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
