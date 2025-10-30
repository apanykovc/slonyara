from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


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
