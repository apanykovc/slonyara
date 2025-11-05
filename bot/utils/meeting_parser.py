"""Utilities for parsing free-form meeting commands from chat messages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Optional, Tuple

_DATE_RE = re.compile(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?$")
_TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")
_NUMBER_RE = re.compile(r"^\d+$")


@dataclass(slots=True)
class MeetingCommand:
    """Structured representation of a meeting-related command."""

    action: str
    request_number: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    date_parts: Optional[Tuple[int, int, Optional[int]]] = None
    time_parts: Optional[Tuple[int, int]] = None
    meeting_type: Optional[str] = None
    room: Optional[str] = None
    new_request_number: Optional[str] = None
    minutes_delta: Optional[int] = None
    chat_id: Optional[int] = None


def parse_meeting_command(
    text: str, now: datetime
) -> Tuple[Optional[MeetingCommand], Optional[str]]:
    """Parse a chat message into a structured command.

    Returns a tuple of ``(command, error_message)``. Only one element of the
    tuple will be non-``None``:

    * ``command`` – a structured representation of the recognised command.
    * ``error_message`` – a human friendly explanation of why parsing failed.
    """

    text = text.strip()
    if not text:
        return None, None

    chat_id, remainder = _extract_chat_prefix(text)
    text = remainder.strip()
    if not text:
        return None, None

    lower = text.lower()

    command, error = _parse_create(text, now)
    if command:
        command.chat_id = chat_id
        return command, None
    if error:
        return None, error

    command = _parse_cancel(lower)
    if command:
        command.chat_id = chat_id
        return command, None

    command = _parse_snooze(lower)
    if command:
        command.chat_id = chat_id
        return command, None

    command = _parse_update(text, lower, now)
    if command:
        command.chat_id = chat_id
        return command, None

    return None, None


def _extract_chat_prefix(text: str) -> Tuple[Optional[int], str]:
    parts = text.split(maxsplit=1)
    if not parts:
        return None, text
    token = parts[0]
    if token.lower().startswith("chat:"):
        candidate = token[5:]
    elif token.startswith("#"):
        candidate = token[1:]
    else:
        return None, text
    try:
        chat_id = int(candidate)
    except ValueError:
        return None, text
    remainder = parts[1] if len(parts) > 1 else ""
    return chat_id, remainder


def _parse_create(
    text: str, now: datetime
) -> Tuple[Optional[MeetingCommand], Optional[str]]:
    parts = text.split()
    if len(parts) != 5:
        return (
            None,
            "Не удалось распознать команду. Используйте формат: "
            "ДД.ММ ТИП ЧЧ:ММ ПЕРЕГОВОРНАЯ НОМЕР.\n"
            "Например: 25.03 DEMO 14:00 R101 12345",
        )

    date_token, type_token, time_token, room_token, number_token = parts
    date_parts = _parse_date_token(date_token)
    time_parts = _parse_time_token(time_token)
    if not date_parts:
        return (
            None,
            "Некорректная дата. Используйте формат ДД.ММ или ДД.ММ.ГГГГ.\n"
            "Например: 25.03 или 25.03.2024",
        )
    if not time_parts:
        return (
            None,
            "Некорректное время. Используйте формат ЧЧ:ММ (24 часа).\n"
            "Например: 14:00",
        )
    if not _NUMBER_RE.match(number_token):
        return (
            None,
            "Некорректный номер заявки. Укажите только цифры.\n"
            "Например: 12345",
        )

    scheduled_at = _build_datetime(*date_parts, *time_parts, now=now)
    if scheduled_at is None:
        return (
            None,
            "Некорректная дата или время. Проверьте существование даты.\n"
            "Например: 29.02.2024 10:00",
        )

    meeting_type = _normalize_type(type_token)
    room = _normalize_room(room_token)
    return (
        MeetingCommand(
            action="create",
            request_number=number_token,
            scheduled_at=scheduled_at,
            meeting_type=meeting_type,
            room=room,
        ),
        None,
    )


def _parse_cancel(lower: str) -> Optional[MeetingCommand]:
    match = re.match(r"^(?:отмена|cancel)\s+(?P<number>\d+)$", lower)
    if not match:
        match = re.match(r"^(?P<number>\d+)\s+(?:отмена|cancel)$", lower)
    if not match:
        return None
    return MeetingCommand(action="cancel", request_number=match.group("number"))


def _parse_snooze(lower: str) -> Optional[MeetingCommand]:
    match = re.match(
        r"^\+(?P<minutes>\d{1,3})(?:\s*(?:мин(?:ут[ы]?)?)?)?(?:\s+(?P<number>\d+))?$",
        lower,
    )
    if not match:
        match = re.match(
            r"^(?P<number>\d+)\s*\+(?P<minutes>\d{1,3})(?:\s*(?:мин(?:ут[ы]?)?)?)?$",
            lower,
        )
    if not match:
        return None
    minutes = int(match.group("minutes"))
    request_number = match.groupdict().get("number")
    return MeetingCommand(action="snooze", request_number=request_number, minutes_delta=minutes)


def _parse_update(text: str, lower: str, now: datetime) -> Optional[MeetingCommand]:
    match = re.match(r"^(?P<number>\d+)\s+(?P<time>\d{1,2}:\d{2})$", lower)
    if match:
        time_parts = _parse_time_token(match.group("time"))
        if not time_parts:
            return None
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            time_parts=time_parts,
        )

    match = re.match(
        r"^(?P<number>\d+)\s+(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+(?P<time>\d{1,2}:\d{2})$",
        lower,
    )
    if match:
        date_parts = _parse_date_token(match.group("date"))
        time_parts = _parse_time_token(match.group("time"))
        if not date_parts or not time_parts:
            return None
        scheduled_at = _build_datetime(*date_parts, *time_parts, now=now)
        if scheduled_at is None:
            return None
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            scheduled_at=scheduled_at,
        )

    match = re.match(r"^(?P<number>\d+)\s+(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)$", lower)
    if match:
        date_parts = _parse_date_token(match.group("date"))
        if not date_parts:
            return None
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            date_parts=date_parts,
        )

    match = re.match(r"^(?P<number>\d+)\s+(?:тип|type)\s+(?P<type>.+)$", lower)
    if match:
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            meeting_type=_normalize_type(match.group("type")),
        )

    match = re.match(r"^(?P<number>\d+)\s+(?:комната|переговорная|room)\s+(?P<room>\S+)$", lower)
    if match:
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            room=_normalize_room(match.group("room")),
        )

    match = re.match(r"^(?P<number>\d+)\s+(?:номер|заявка|ticket)\s+(?P<new>\d+)$", lower)
    if match:
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            new_request_number=match.group("new"),
        )

    match = re.match(
        r"^(?:перенос|перенести)\s+(?P<number>\d+)(?:\s+(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?))?(?:\s+(?P<time>\d{1,2}:\d{2}))?$",
        lower,
    )
    if not match:
        match = re.match(
            r"^(?P<number>\d+)\s+(?:перенос|перенести)\s+(?:(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+)?(?P<time>\d{1,2}:\d{2})$",
            lower,
        )
    if match:
        date_parts = _parse_optional_date(match.group("date"))
        time_parts = _parse_optional_time(match.group("time"))
        scheduled_at = None
        if date_parts and time_parts:
            scheduled_at = _build_datetime(*date_parts, *time_parts, now=now)
        return MeetingCommand(
            action="update",
            request_number=match.group("number"),
            date_parts=None if scheduled_at else date_parts,
            time_parts=None if scheduled_at else time_parts,
            scheduled_at=scheduled_at,
        )

    return None


def _parse_date_token(token: str) -> Optional[Tuple[int, int, Optional[int]]]:
    match = _DATE_RE.match(token)
    if not match:
        return None
    day = int(match.group("day"))
    month = int(match.group("month"))
    year_text = match.group("year")
    year: Optional[int] = None
    if year_text is not None:
        year = int(year_text)
        if year < 100:
            year += 2000
    return day, month, year


def _parse_time_token(token: str) -> Optional[Tuple[int, int]]:
    match = _TIME_RE.match(token)
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _parse_optional_date(token: Optional[str]) -> Optional[Tuple[int, int, Optional[int]]]:
    if token is None:
        return None
    return _parse_date_token(token)


def _parse_optional_time(token: Optional[str]) -> Optional[Tuple[int, int]]:
    if token is None:
        return None
    return _parse_time_token(token)


def _build_datetime(
    day: int,
    month: int,
    year: Optional[int],
    hour: int,
    minute: int,
    *,
    now: datetime,
) -> Optional[datetime]:
    reference = now.replace(tzinfo=None)
    try:
        if year is not None:
            return datetime(year, month, day, hour, minute)
        candidate = datetime(reference.year, month, day, hour, minute)
        if candidate < reference:
            candidate = datetime(reference.year + 1, month, day, hour, minute)
        return candidate
    except ValueError:
        return None


def _normalize_type(raw: str) -> str:
    return raw.strip().upper()


def _normalize_room(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")


__all__ = ["MeetingCommand", "parse_meeting_command"]
