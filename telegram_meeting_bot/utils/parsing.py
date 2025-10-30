from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import NamedTuple

from zoneinfo import ZoneInfo

from .datetime import now_utc

STRICT_RE = re.compile(r"^(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+(?P<tag>\S+)\s+(?P<time>\d{1,2}:\d{2})\s+(?P<room>\S+)\s+(?P<ticket>\S+)")


class ParsedEvent(NamedTuple):
    starts_at: datetime
    tag: str
    room: str
    ticket: str


def _interpret_date(date_str: str, reference: datetime, tz: ZoneInfo) -> datetime:
    parts = date_str.split(".")
    day = int(parts[0])
    month = int(parts[1])
    if len(parts) > 2:
        year = int(parts[2])
        if year < 100:
            year += 2000
    else:
        year = reference.astimezone(tz).year
    return datetime(year, month, day)


def parse_strict(text: str, tz_name: str) -> ParsedEvent | None:
    match = STRICT_RE.match(text.strip())
    if not match:
        return None
    now = now_utc()
    tz = ZoneInfo(tz_name)
    date_value = _interpret_date(match.group("date"), now, tz)
    hour, minute = map(int, match.group("time").split(":"))
    local_dt = datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
        tzinfo=tz,
    )
    starts_at = local_dt.astimezone(tz=ZoneInfo("UTC"))
    return ParsedEvent(
        starts_at=starts_at,
        tag=match.group("tag"),
        room=match.group("room"),
        ticket=match.group("ticket"),
    )


def parse_natural(text: str, tz_name: str) -> ParsedEvent | None:
    text = text.strip()
    tokens = text.split()
    if len(tokens) < 5:
        return None
    now = now_utc()
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)

    date_token = tokens[0].lower()
    if date_token in {"завтра", "tomorrow"}:
        date_value = local_now + timedelta(days=1)
    elif date_token in {"послезавтра", "aftertomorrow"}:
        date_value = local_now + timedelta(days=2)
    elif re.match(r"\d{1,2}\.\d{1,2}", date_token):
        parsed = datetime.strptime(date_token, "%d.%m")
        date_value = parsed.replace(year=local_now.year)
    else:
        return None

    time_token = tokens[1]
    if not re.match(r"\d{1,2}:\d{2}", time_token):
        return None
    hour, minute = map(int, time_token.split(":"))

    local_dt = datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
        tzinfo=tz,
    )
    starts_at = local_dt.astimezone(tz=ZoneInfo("UTC"))

    return ParsedEvent(
        starts_at=starts_at,
        tag=tokens[2],
        room=tokens[3],
        ticket=tokens[4],
    )


def parse_event(text: str, tz_name: str) -> ParsedEvent | None:
    return parse_strict(text, tz_name) or parse_natural(text, tz_name)
