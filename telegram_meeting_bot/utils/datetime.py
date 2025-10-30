from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc


def aware_from_naive(date: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if date.tzinfo is None:
        date = date.replace(tzinfo=tz)
    return date.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return dt.astimezone(tz)


def combine_date_time(date_value: datetime, time_value: time, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    combined = datetime.combine(date_value.date(), time_value, tzinfo=tz)
    return combined.astimezone(UTC)


def next_occurrence(start: datetime, repeat: str) -> datetime | None:
    if repeat == "daily":
        return start + timedelta(days=1)
    if repeat == "weekly":
        return start + timedelta(weeks=1)
    return None
