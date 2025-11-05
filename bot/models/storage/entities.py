"""Data structures for meetings, chats and user settings."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from zoneinfo import ZoneInfo

from .utils import RoleName, ensure_timezone, normalize_lead_times, normalize_role


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
    status: str = "planned"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
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
            "status": self.status,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], *, timezone: ZoneInfo | None = None) -> "Meeting":
        scheduled = datetime.fromisoformat(str(payload["scheduled_at"]))
        if timezone is not None:
            scheduled = ensure_timezone(scheduled, timezone)
        created_raw = payload.get("created_at")
        updated_raw = payload.get("updated_at")
        created_at = datetime.fromisoformat(created_raw) if created_raw else None
        updated_at = datetime.fromisoformat(updated_raw) if updated_raw else None
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title", "")),
            scheduled_at=scheduled,
            organizer_id=int(payload.get("organizer_id", 0)),
            participants=[int(pid) for pid in payload.get("participants", [])],
            description=payload.get("description"),
            reminder_sent=bool(payload.get("reminder_sent", False)),
            meeting_type=payload.get("meeting_type"),
            room=payload.get("room"),
            request_number=payload.get("request_number"),
            chat_id=payload.get("chat_id"),
            status=str(payload.get("status", "planned")),
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(slots=True)
class ChatSettings:
    """Persistent settings and permissions for a chat."""

    id: int
    title: str = ""
    lead_times: List[int] = field(default_factory=list)
    admin_ids: List[int] = field(default_factory=list)
    roles: Dict[int, RoleName] = field(default_factory=dict)
    reminder_log: Dict[str, List[int]] = field(default_factory=dict)
    timezone: Optional[str] = None
    default_lead: Optional[int] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "lead_times": self.lead_times,
            "admin_ids": self.admin_ids,
            "roles": {str(user_id): role for user_id, role in self.roles.items()},
            "reminder_log": self.reminder_log,
            "timezone": self.timezone,
            "default_lead": self.default_lead,
            "is_active": self.is_active,
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

        roles_payload = payload.get("roles", {}) or {}
        roles: dict[int, RoleName] = {}
        for raw_user_id, raw_role in roles_payload.items():
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue
            role = normalize_role(raw_role)
            if role is None:
                continue
            roles[user_id] = role

        for admin_id in admin_ids:
            roles.setdefault(admin_id, "admin")
        for user_id, role in list(roles.items()):
            if role == "admin" and user_id not in admin_ids:
                admin_ids.append(user_id)

        admin_ids = list(dict.fromkeys(admin_ids))

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
            roles=roles,
            reminder_log=reminder_log,
            timezone=payload.get("timezone"),
            default_lead=payload.get("default_lead"),
            is_active=bool(payload.get("is_active", True)),
        )


@dataclass(slots=True)
class UserSettings:
    """Persistent preferences for an individual user."""

    id: int
    timezone: Optional[str] = None
    locale: str = "ru_RU"
    date_format: str = "%d.%m.%Y"
    time_format: str = "%H:%M"
    default_lead_time: int = 900
    role: RoleName = "user"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "timezone": self.timezone,
            "locale": self.locale,
            "date_format": self.date_format,
            "time_format": self.time_format,
            "default_lead_time": self.default_lead_time,
            "role": self.role,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UserSettings":
        timezone_value = payload.get("timezone")
        if timezone_value:
            timezone_value = str(timezone_value)
        default_lead_time = payload.get("default_lead_time", 900)
        try:
            default_lead_time = int(default_lead_time)
        except (TypeError, ValueError):
            default_lead_time = 900
        if default_lead_time < 0:
            default_lead_time = 0
        created_raw = payload.get("created_at")
        updated_raw = payload.get("updated_at")
        created_at = datetime.fromisoformat(created_raw) if created_raw else None
        updated_at = datetime.fromisoformat(updated_raw) if updated_raw else None
        role = normalize_role(payload.get("role")) or "user"
        return cls(
            id=int(payload.get("id", 0)),
            timezone=timezone_value,
            locale=str(payload.get("locale", "ru_RU")),
            date_format=str(payload.get("date_format", "%d.%m.%Y")),
            time_format=str(payload.get("time_format", "%H:%M")),
            default_lead_time=default_lead_time,
            role=role,
            created_at=created_at,
            updated_at=updated_at,
        )


def ensure_chat_defaults(
    chat: ChatSettings,
    *,
    default_lead_times: Iterable[int] | None,
    default_timezone: str | None,
) -> ChatSettings:
    """Apply default values for chat-specific settings."""

    if not chat.lead_times:
        default = tuple(default_lead_times or (1800, 600, 0))
        chat.lead_times = list(default)
    chat.lead_times = normalize_lead_times(chat.lead_times)
    if not chat.timezone and default_timezone:
        chat.timezone = default_timezone
    normalized_roles: dict[int, RoleName] = {}
    for user_id, role in chat.roles.items():
        try:
            normalized_user = int(user_id)
        except (TypeError, ValueError):
            continue
        normalized_role = normalize_role(role)
        if normalized_role is None:
            continue
        normalized_roles[normalized_user] = normalized_role
    chat.roles = normalized_roles
    chat.admin_ids = [user_id for user_id, role in chat.roles.items() if role == "admin"]
    chat.reminder_log = {
        meeting_id: normalize_lead_times(values)
        for meeting_id, values in chat.reminder_log.items()
    }
    return chat


def ensure_user_defaults(
    settings: UserSettings,
    *,
    default_lead_time: int,
    default_locale: str,
    default_timezone: str | None,
) -> UserSettings:
    """Normalize user settings with defaults from configuration."""

    if settings.created_at is None:
        settings.default_lead_time = default_lead_time
    if not settings.locale or settings.created_at is None:
        settings.locale = default_locale
    if not settings.timezone and default_timezone:
        settings.timezone = default_timezone
    if not settings.date_format:
        settings.date_format = "%d.%m.%Y"
    if not settings.time_format:
        settings.time_format = "%H:%M"
    if settings.default_lead_time < 0:
        settings.default_lead_time = 0
    if settings.role not in ("admin", "user"):
        settings.role = "user"
    return settings


__all__ = [
    "ChatSettings",
    "Meeting",
    "UserSettings",
    "ensure_chat_defaults",
    "ensure_user_defaults",
]
