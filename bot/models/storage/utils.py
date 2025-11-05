"""Shared helper utilities for storage layer modules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, List, Sequence, Tuple, cast, Literal

from zoneinfo import ZoneInfo

RoleName = Literal["admin", "user"]

_VALID_ROLES: Tuple[RoleName, ...] = ("admin", "user")


def normalize_role(value: Any) -> RoleName | None:
    """Normalize a role value into the canonical :class:`RoleName`."""

    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _VALID_ROLES:
        return cast(RoleName, text)
    return None


def utcnow() -> str:
    """Return a timezone-aware ISO timestamp in UTC."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_timezone(dt: datetime, tz: ZoneInfo | None) -> datetime:
    """Attach or convert a datetime to the configured timezone."""

    if dt.tzinfo is None:
        if tz is not None:
            return dt.replace(tzinfo=tz)
        return dt.replace(tzinfo=timezone.utc)
    if tz is None:
        return dt
    return dt.astimezone(tz)


def normalize_lead_times(values: Sequence[int] | Iterable[int]) -> List[int]:
    """Return a sorted list of unique non-negative lead times in seconds."""

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


__all__ = [
    "RoleName",
    "normalize_role",
    "normalize_lead_times",
    "ensure_timezone",
    "utcnow",
]
