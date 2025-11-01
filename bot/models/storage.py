"""Persistence layer for meetings and bot settings."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
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
    meeting_type: Optional[str] = None
    room: Optional[str] = None
    request_number: Optional[str] = None
    chat_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scheduled_at": self.scheduled_at.isoformat(),
            "organizer_id": self.organizer_id,
            "participants": self.participants,
            "description": self.description,
            "reminder_sent": self.reminder_sent,
            "meeting_type": self.meeting_type,
            "room": self.room,
            "request_number": self.request_number,
            "chat_id": self.chat_id,
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
            meeting_type=payload.get("meeting_type"),
            room=payload.get("room"),
            request_number=payload.get("request_number"),
            chat_id=payload.get("chat_id"),
        )


@dataclass(slots=True)
class ChatSettings:
    """Persistent settings and permissions for a chat."""

    id: int
    title: str = ""
    lead_times: List[int] = field(default_factory=list)
    admin_ids: List[int] = field(default_factory=list)
    reminder_log: Dict[str, List[int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "lead_times": self.lead_times,
            "admin_ids": self.admin_ids,
            "reminder_log": self.reminder_log,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ChatSettings":
        lead_times: list[int] = []
        for value in payload.get("lead_times", []) or []:
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                continue
            if seconds < 0:
                continue
            lead_times.append(seconds)
        admin_ids: list[int] = []
        for value in payload.get("admin_ids", []) or []:
            try:
                admin_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        reminder_log: dict[str, list[int]] = {}
        for key, values in (payload.get("reminder_log", {}) or {}).items():
            normalized: list[int] = []
            for value in values:
                try:
                    normalized.append(int(value))
                except (TypeError, ValueError):
                    continue
            reminder_log[str(key)] = normalized
        return cls(
            id=int(payload["id"]),
            title=str(payload.get("title", "")),
            lead_times=lead_times,
            admin_ids=admin_ids,
            reminder_log=reminder_log,
        )


class MeetingStorage:
    """Simple JSON based storage implementation."""

    def __init__(
        self,
        path: Path,
        timezone: ZoneInfo | None = None,
        *,
        default_lead_times: Sequence[int] | None = None,
    ) -> None:
        self._path = path
        self._timezone = timezone
        self._default_lead_times: tuple[int, ...] = tuple(default_lead_times or ())
        self._data: Dict[str, Any] = {"meetings": [], "settings": {}, "chats": []}
        self._load()

    @property
    def timezone(self) -> ZoneInfo | None:
        """Return configured timezone, if any."""

        return self._timezone

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
            self._data.setdefault("meetings", [])
            self._data.setdefault("settings", {})
            self._data.setdefault("chats", [])
        except json.JSONDecodeError:
            _logger.exception("Failed to decode storage file %s, starting fresh", self._path)
            self._data = {"meetings": [], "settings": {}, "chats": []}
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

    def _chats(self) -> List[Dict[str, Any]]:
        return self._data.setdefault("chats", [])

    def list_meetings(self) -> List[Meeting]:
        meetings = [Meeting.from_dict(payload) for payload in self._meetings()]
        meetings.sort(key=lambda meeting: meeting.scheduled_at)
        return meetings

    def list_meetings_for_user(self, user_id: int, *, chat_id: Optional[int] = None) -> List[Meeting]:
        meetings = [meeting for meeting in self.list_meetings() if user_id in meeting.participants]
        if chat_id is not None:
            meetings = [meeting for meeting in meetings if meeting.chat_id == chat_id]
        return meetings

    def list_meetings_for_chat(self, chat_id: int) -> List[Meeting]:
        return [meeting for meeting in self.list_meetings() if meeting.chat_id == chat_id]

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                return Meeting.from_dict(payload)
        return None

    def find_meeting_by_request_number(self, request_number: str) -> Optional[Meeting]:
        for payload in self._meetings():
            if payload.get("request_number") == request_number:
                return Meeting.from_dict(payload)
        return None

    def create_meeting(
        self,
        title: str,
        scheduled_at: datetime,
        organizer_id: int,
        participants: Optional[Iterable[int]] = None,
        description: Optional[str] = None,
        *,
        meeting_type: Optional[str] = None,
        room: Optional[str] = None,
        request_number: Optional[str] = None,
        chat_id: Optional[int] = None,
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
            meeting_type=meeting_type,
            room=room,
            request_number=request_number,
            chat_id=chat_id,
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
        self._remove_meeting_reminders(meeting_id)
        self._save()
        return True

    def reschedule_meeting(self, meeting_id: str, scheduled_at: datetime) -> bool:
        scheduled_at = self._with_timezone(scheduled_at)
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                payload["scheduled_at"] = scheduled_at.isoformat()
                payload["reminder_sent"] = False
                self._remove_chat_reminder_entries(meeting_id)
                self._save()
                return True
        return False

    def update_meeting(
        self,
        meeting_id: str,
        *,
        title: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
        meeting_type: Optional[str] = None,
        room: Optional[str] = None,
        request_number: Optional[str] = None,
    ) -> Optional[Meeting]:
        if scheduled_at is not None:
            scheduled_at = self._with_timezone(scheduled_at)
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                if title is not None:
                    payload["title"] = title
                if scheduled_at is not None:
                    payload["scheduled_at"] = scheduled_at.isoformat()
                    payload["reminder_sent"] = False
                    self._remove_chat_reminder_entries(meeting_id)
                if meeting_type is not None:
                    payload["meeting_type"] = meeting_type
                if room is not None:
                    payload["room"] = room
                if request_number is not None:
                    payload["request_number"] = request_number
                self._save()
                return Meeting.from_dict(payload)
        return None

    def mark_reminder_sent(self, meeting_id: str, chat_id: int, lead_time: int) -> None:
        for chat_payload in self._chats():
            if int(chat_payload.get("id")) != chat_id:
                continue
            reminders = chat_payload.setdefault("reminder_log", {})
            sent_leads = reminders.setdefault(meeting_id, [])
            if lead_time not in sent_leads:
                sent_leads.append(lead_time)
                sent_leads.sort()
            break
        for payload in self._meetings():
            if payload.get("id") == meeting_id and lead_time == 0:
                payload["reminder_sent"] = True
                break
        self._save()

    def is_reminder_sent(self, meeting_id: str, chat_id: int, lead_time: int) -> bool:
        for chat_payload in self._chats():
            if int(chat_payload.get("id")) != chat_id:
                continue
            reminders = chat_payload.get("reminder_log", {})
            sent = reminders.get(meeting_id, [])
            return lead_time in sent
        return False

    # ------------------------------------------------------------------
    # chat helpers
    def list_chats(self) -> List[ChatSettings]:
        return [self._ensure_chat_defaults(ChatSettings.from_dict(payload)) for payload in self._chats()]

    def get_chat(self, chat_id: int) -> Optional[ChatSettings]:
        for payload in self._chats():
            if int(payload.get("id")) == chat_id:
                return self._ensure_chat_defaults(ChatSettings.from_dict(payload))
        return None

    def is_chat_registered(self, chat_id: int) -> bool:
        return self.get_chat(chat_id) is not None

    def register_chat(
        self,
        chat_id: int,
        title: Optional[str],
        *,
        lead_times: Sequence[int] | None = None,
        admin_ids: Iterable[int] | None = None,
    ) -> ChatSettings:
        if lead_times is None:
            lead_times = self._default_lead_times or (1800, 600, 0)
        admins: list[int] = []
        for candidate in admin_ids or []:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value not in admins:
                admins.append(value)
        normalized_leads = self._normalize_lead_times(lead_times)
        if not normalized_leads:
            normalized_leads = self._normalize_lead_times(self._default_lead_times or (1800, 600, 0))

        for payload in self._chats():
            if int(payload.get("id")) == chat_id:
                if title:
                    payload["title"] = title
                payload.setdefault("lead_times", normalized_leads)
                payload.setdefault("admin_ids", [])
                payload.setdefault("reminder_log", {})
                for admin_id in admins:
                    if admin_id not in payload["admin_ids"]:
                        payload["admin_ids"].append(admin_id)
                payload["lead_times"] = normalized_leads
                self._save()
                return self._ensure_chat_defaults(ChatSettings.from_dict(payload))

        chat = ChatSettings(
            id=chat_id,
            title=title or "",
            lead_times=list(normalized_leads),
            admin_ids=admins,
        )
        self._chats().append(chat.to_dict())
        self._save()
        return self._ensure_chat_defaults(chat)

    def set_chat_lead_times(self, chat_id: int, lead_times: Sequence[int]) -> Optional[ChatSettings]:
        normalized = self._normalize_lead_times(lead_times)
        if not normalized:
            return None
        for payload in self._chats():
            if int(payload.get("id")) == chat_id:
                payload["lead_times"] = normalized
                payload.setdefault("reminder_log", {})
                self._save()
                return self._ensure_chat_defaults(ChatSettings.from_dict(payload))
        return None

    def add_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        for payload in self._chats():
            if int(payload.get("id")) == chat_id:
                admins = payload.setdefault("admin_ids", [])
                if user_id not in admins:
                    admins.append(user_id)
                    self._save()
                return self._ensure_chat_defaults(ChatSettings.from_dict(payload))
        return None

    def remove_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        for payload in self._chats():
            if int(payload.get("id")) == chat_id:
                admins = payload.setdefault("admin_ids", [])
                if user_id in admins:
                    admins.remove(user_id)
                    self._save()
                return self._ensure_chat_defaults(ChatSettings.from_dict(payload))
        return None

    def is_chat_admin(self, chat_id: int, user_id: int) -> bool:
        chat = self.get_chat(chat_id)
        if not chat:
            return False
        return user_id in chat.admin_ids

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

    def _ensure_chat_defaults(self, chat: ChatSettings) -> ChatSettings:
        if not chat.lead_times:
            default = self._default_lead_times or (1800, 600, 0)
            chat.lead_times = list(default)
        chat.lead_times = self._normalize_lead_times(chat.lead_times)
        chat.admin_ids = list(dict.fromkeys(chat.admin_ids))
        chat.reminder_log = {
            meeting_id: self._normalize_lead_times(values)
            for meeting_id, values in chat.reminder_log.items()
        }
        return chat

    def _normalize_lead_times(self, values: Sequence[int] | Iterable[int]) -> List[int]:
        normalized: list[int] = []
        for value in values:
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                continue
            if seconds < 0:
                continue
            normalized.append(seconds)
        if not normalized:
            return []
        return sorted(dict.fromkeys(normalized))

    def _remove_chat_reminder_entries(self, meeting_id: str) -> None:
        for payload in self._chats():
            reminders = payload.setdefault("reminder_log", {})
            if meeting_id in reminders:
                reminders.pop(meeting_id, None)

    def _remove_meeting_reminders(self, meeting_id: str) -> None:
        self._remove_chat_reminder_entries(meeting_id)
        for payload in self._meetings():
            if payload.get("id") == meeting_id:
                payload["reminder_sent"] = False
                break
