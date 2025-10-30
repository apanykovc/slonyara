from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


RepeatType = Literal["none", "daily", "weekly"]


@dataclass(slots=True)
class Event:
    id: str
    creator_id: int
    chat_id: Optional[int]
    thread_id: Optional[int]
    target_chat_id: Optional[int]
    title: str
    room: str
    ticket: str
    starts_at: datetime
    created_at: datetime
    lead_time_minutes: int
    repeat: RepeatType = "none"
    cancelled: bool = False
    last_fired_at: Optional[datetime] = None


@dataclass(slots=True)
class EventReminder:
    event_id: str
    due_at: datetime
