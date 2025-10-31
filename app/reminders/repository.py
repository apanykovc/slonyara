"""In-memory repository for reminders.

The project is intentionally small and does not use a real database.  The
repository implements the minimum CRUD surface required by the scheduling
service so that the behaviour can be unit tested.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .models import Reminder


class ReminderRepository:
    """Store reminders in memory."""

    def __init__(self) -> None:
        self._storage: Dict[str, Dict[str, Reminder]] = {}

    # CRUD helpers -----------------------------------------------------
    def upsert(self, reminder: Reminder) -> Reminder:
        self._storage.setdefault(reminder.meeting_id, {})[reminder.id] = reminder
        return reminder

    def delete_meeting(self, meeting_id: str) -> List[Reminder]:
        return list(self._storage.pop(meeting_id, {}).values())

    def get(self, meeting_id: str, reminder_id: str) -> Optional[Reminder]:
        return self._storage.get(meeting_id, {}).get(reminder_id)

    def list_for_meeting(self, meeting_id: str) -> List[Reminder]:
        return list(self._storage.get(meeting_id, {}).values())

    # domain helpers ---------------------------------------------------
    def mark_sent(self, meeting_id: str, reminder_id: str, sent_at: datetime) -> Optional[Reminder]:
        reminder = self.get(meeting_id, reminder_id)
        if reminder is None:
            return None
        reminder.sent_at = sent_at
        return reminder
