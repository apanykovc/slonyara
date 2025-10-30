from __future__ import annotations

from ..locales import get_text
from .datetime import to_local


def format_event_line(
    event,
    tz: str,
    language: str,
    *,
    include_date: bool = True,
    include_ticket: bool = True,
    suffix: str | None = None,
) -> str:
    """Return a short human-friendly description of an event."""

    local_time = to_local(event.starts_at, tz)
    time_format = "%d.%m %H:%M" if include_date else "%H:%M"
    prefix = local_time.strftime(time_format)

    parts: list[str] = []
    if event.title:
        parts.append(event.title)
    if event.room:
        parts.append(event.room)
    if include_ticket and event.ticket:
        label = get_text(language, "ticket_label")
        parts.append(f"{label} {event.ticket}")

    body = " · ".join(parts)
    line = f"{prefix} — {body}" if body else prefix
    if suffix:
        line = f"{line} ({suffix})"
    return line
