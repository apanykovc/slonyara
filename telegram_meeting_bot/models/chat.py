from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class ChatSettings:
    chat_id: int
    title: str
    timezone: str
    lead_time_minutes: int
    quiet_hours_start: Optional[int] = None
    quiet_hours_end: Optional[int] = None
    language: str = "ru"
    registered: bool = False
    message_thread_id: Optional[int] = None
    last_digest_sent: Optional[datetime] = None


@dataclass(slots=True)
class ChatRole:
    chat_id: int
    user_id: int
    role: str
