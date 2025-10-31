"""Persistence layer for meetings and bot settings."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Meeting:
    """Data container that represents a planned meeting."""

    id: str
    title: str
    scheduled_at: datetime
    organizer_id: int
    participants: List[int] = field(default_factory=list)
    description: Optional[str] = None
    reminder_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scheduled_at": self.scheduled_at.isoformat(),
            "organizer_id": self.organizer_id,
            "participants": self.participants,
            "description": self.description,
            "reminder_sent": self.reminder_sent,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Meeting":
        return cls(
            id=payload["id"],
            title=payload.get("title", ""),
            scheduled_at=datetime.fromisoformat(payload["scheduled_at"]),
            organizer_id=int(payload.get("organizer_id", 0)),
            participants=[int(pid) for pid in payload.get("participants", [])],
            description=payload.get("description"),
            reminder_sent=bool(payload.get("reminder_sent", False)),
        )


class MeetingStorage:
    """Simple JSON based storage implementation."""

    def __init__(self, path: Path, timezone: ZoneInfo | None = None) -> None:
        self._path = path
        self._timezone = timezone
        self._data: Dict[str, Any] = {"meetings": [], "settings": {}}
        self._load()

    # ------------------------------------------------------------------
    # persistence helpers
    def _load(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except json.JSONDecodeError:
            _logger.exception("Failed to decode storage file %s, starting fresh", self._path)
            self._data = {"meetings": [], "settings": {}}
        except OSError:
            _logger.exception("Failed to read storage file %s", self._path)

    def _save(self) -> None:
        temp_file = self._path.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        temp_file.replace(self._path)

    # ------------------------------------------------------------------
    # meeting management
    def _meetings(self) -> List[Dict[str, Any]]:
        return self._data.setdefault("meetings", [])

    def list_meetings(self) -> List[Meeting]:
        meetings = [Meeting.from_dict(payload) for payload in self._meetings()]
        meetings.sort(key=lambda meeting: meeting.scheduled_at)
        return meetings

    def list_meetings_for_user(self, user_id: int) -> List[Meeting]:
        return [meeting for meeting in self.list_meetings() if user_id in meeting.participants]

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                return Meeting.from_dict(payload)
        return None

    def create_meeting(
        self,
        title: str,
        scheduled_at: datetime,
        organizer_id: int,
        participants: Optional[Iterable[int]] = None,
        description: Optional[str] = None,
    ) -> Meeting:
        if participants is None:
            participants = [organizer_id]
        meeting = Meeting(
            id=str(uuid4()),
            title=title,
            scheduled_at=self._with_timezone(scheduled_at),
            organizer_id=organizer_id,
            participants=list(dict.fromkeys(int(pid) for pid in participants)),
            description=description,
        )
        self._meetings().append(meeting.to_dict())
        self._save()
        return meeting

    def cancel_meeting(self, meeting_id: str) -> bool:
        meetings = self._meetings()
        filtered = [payload for payload in meetings if payload.get("id") != meeting_id]
        if len(filtered) == len(meetings):
            return False
        self._data["meetings"] = filtered
        self._save()
        return True

    def reschedule_meeting(self, meeting_id: str, scheduled_at: datetime) -> bool:
        scheduled_at = self._with_timezone(scheduled_at)
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                payload["scheduled_at"] = scheduled_at.isoformat()
                payload["reminder_sent"] = False
                self._save()
                return True
        return False

    def mark_reminder_sent(self, meeting_id: str) -> None:
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                payload["reminder_sent"] = True
                self._save()
                break

    def get_due_meetings(self, now: datetime, lead_time: int) -> List[Meeting]:
        result: list[Meeting] = []
        for payload in self._meetings():
            meeting = Meeting.from_dict(payload)
            delta = meeting.scheduled_at - now
            if 0 <= delta.total_seconds() <= lead_time and not meeting.reminder_sent:
                result.append(meeting)
        result.sort(key=lambda meeting: meeting.scheduled_at)
        return result

    # ------------------------------------------------------------------
    # settings helpers
    def get_setting(self, name: str, default: Any = None) -> Any:
        return self._data.setdefault("settings", {}).get(name, default)

    def set_setting(self, name: str, value: Any) -> None:
        self._data.setdefault("settings", {})[name] = value
        self._save()

    # ------------------------------------------------------------------
    def _with_timezone(self, dt: datetime) -> datetime:
        if self._timezone is None:
            return dt
        if dt.tzinfo is None:
            return dt.replace(tzinfo=self._timezone)
        return dt.astimezone(self._timezone)
