from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class PreferredDestination:
    kind: str  # "self" or "chat"
    chat_id: Optional[int] = None
    thread_id: Optional[int] = None


@dataclass(slots=True)
class UserSettings:
    user_id: int
    timezone: str
    lead_time_minutes: int
    language: str = "ru"
    quiet_hours_start: Optional[int] = None
    quiet_hours_end: Optional[int] = None
    direct_notifications: bool = True
    last_digest_sent: Optional[datetime] = None
    preferred_destination: Optional[PreferredDestination] = None

    def __post_init__(self) -> None:
        if isinstance(self.preferred_destination, dict):
            self.preferred_destination = PreferredDestination(**self.preferred_destination)
