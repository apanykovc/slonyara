"""Domain models for meetings and reminders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Sequence
import uuid


@dataclass(slots=True)
class Reminder:
    """Represents a scheduled reminder that can be sent to a chat."""

    id: str
    meeting_id: str
    chat_id: int
    message: str
    send_at: datetime
    sent_at: datetime | None = None


@dataclass(slots=True)
class Meeting:
    """Represents a meeting with zero or more relative reminder offsets."""

    id: str
    chat_id: int
    title: str
    start_at: datetime
    reminder_offsets: Sequence[timedelta] = field(default_factory=list)

    def iter_absolute_reminders(self, now: datetime | None = None) -> Iterable[tuple[str, datetime]]:
        """Yield reminder identifiers with their absolute ``send_at`` timestamps."""

        now = now or datetime.now(tz=self.start_at.tzinfo)
        for index, offset in enumerate(sorted(self.reminder_offsets, reverse=True)):
            send_at = self.start_at - offset
            if send_at <= now:
                continue
            yield f"{self.id}-reminder-{index}", send_at


def create_meeting(
    chat_id: int,
    title: str,
    start_at: datetime,
    reminder_offsets: Sequence[timedelta] | None = None,
) -> Meeting:
    """Factory for ``Meeting`` instances with automatically generated id."""

    reminder_offsets = list(reminder_offsets or [])
    return Meeting(
        id=str(uuid.uuid4()),
        chat_id=chat_id,
        title=title,
        start_at=start_at,
        reminder_offsets=reminder_offsets,
    )


def create_reminder(
    meeting: Meeting,
    reminder_id: str,
    send_at: datetime,
    message: str,
) -> Reminder:
    """Factory for ``Reminder`` instances bound to a meeting."""

    return Reminder(
        id=reminder_id,
        meeting_id=meeting.id,
        chat_id=meeting.chat_id,
        message=message,
        send_at=send_at,
    )
