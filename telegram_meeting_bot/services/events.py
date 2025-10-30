from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from ..config import BotConfig
from ..models.event import Event
from ..storage.factory import create_storage
from ..utils.datetime import next_occurrence, now_utc, to_local

logger = logging.getLogger("telegram_meeting_bot.services.events")
audit_logger = logging.getLogger("telegram_meeting_bot.audit")


@dataclass(slots=True)
class EventDraft:
    creator_id: int
    chat_id: int | None
    thread_id: int | None
    target_chat_id: int | None
    title: str
    room: str
    ticket: str
    starts_at: datetime
    lead_time_minutes: int
    repeat: str = "none"


class EventConflictError(RuntimeError):
    def __init__(self, draft: EventDraft, conflicts: list[Event]) -> None:
        super().__init__("event conflict detected")
        self.draft = draft
        self.conflicts = conflicts


class EventsService:
    def __init__(self, config: BotConfig) -> None:
        self._storage = create_storage(config, "events", Event, "id")
        self._events: dict[str, Event] = {}
        self._default_lead = config.default_lead_time_minutes
        self._default_duration = timedelta(hours=1)
        self._pending: dict[str, tuple[EventDraft, dict[str, Any]]] = {}

    async def _ensure_cache(self) -> None:
        if self._events:
            return
        items = await self._storage.load_all()
        self._events = {item.id: item for item in items}

    def _make_draft(
        self,
        *,
        creator_id: int,
        chat_id: int | None,
        thread_id: int | None,
        target_chat_id: int | None,
        title: str,
        room: str,
        ticket: str,
        starts_at: datetime,
        lead_time_minutes: int | None,
        repeat: str,
    ) -> EventDraft:
        return EventDraft(
            creator_id=creator_id,
            chat_id=chat_id,
            thread_id=thread_id,
            target_chat_id=target_chat_id,
            title=title,
            room=room,
            ticket=ticket,
            starts_at=starts_at,
            lead_time_minutes=lead_time_minutes or self._default_lead,
            repeat=repeat,
        )

    async def _check_conflicts(
        self,
        draft: EventDraft,
        *,
        exclude_event_id: str | None = None,
        tolerance: timedelta = timedelta(minutes=1),
    ) -> list[Event]:
        await self._ensure_cache()
        conflicts: list[Event] = []
        for event in self._events.values():
            if event.cancelled:
                continue
            if exclude_event_id and event.id == exclude_event_id:
                continue
            if abs((event.starts_at - draft.starts_at).total_seconds()) > tolerance.total_seconds():
                continue
            if event.creator_id == draft.creator_id or event.room.lower() == draft.room.lower():
                conflicts.append(event)
        return conflicts

    def remember_draft(self, draft: EventDraft, *, meta: dict[str, Any] | None = None) -> str:
        token = str(uuid.uuid4())
        self._pending[token] = (draft, meta or {})
        return token

    def get_draft(self, token: str) -> tuple[EventDraft, dict[str, Any]] | None:
        return self._pending.get(token)

    def pop_draft(self, token: str) -> tuple[EventDraft, dict[str, Any]] | None:
        return self._pending.pop(token, None)

    async def create_event(
        self,
        *,
        creator_id: int,
        chat_id: int | None,
        thread_id: int | None,
        target_chat_id: int | None,
        title: str,
        room: str,
        ticket: str,
        starts_at: datetime,
        lead_time_minutes: int | None = None,
        repeat: str = "none",
        allow_conflicts: bool = False,
    ) -> Event:
        await self._ensure_cache()
        draft = self._make_draft(
            creator_id=creator_id,
            chat_id=chat_id,
            thread_id=thread_id,
            target_chat_id=target_chat_id,
            title=title,
            room=room,
            ticket=ticket,
            starts_at=starts_at,
            lead_time_minutes=lead_time_minutes,
            repeat=repeat,
        )
        if not allow_conflicts:
            conflicts = await self._check_conflicts(draft)
            if conflicts:
                raise EventConflictError(draft, conflicts)
        event = Event(
            id=str(uuid.uuid4()),
            creator_id=draft.creator_id,
            chat_id=draft.chat_id,
            thread_id=draft.thread_id,
            target_chat_id=draft.target_chat_id,
            title=draft.title,
            room=draft.room,
            ticket=draft.ticket,
            starts_at=draft.starts_at,
            created_at=now_utc(),
            lead_time_minutes=draft.lead_time_minutes,
            repeat=draft.repeat,
        )
        self._events[event.id] = event
        await self._storage.save_all(self._events.values())
        logger.info("event_created id=%s starts_at=%s", event.id, event.starts_at.isoformat())
        audit_logger.info(
            json.dumps(
                {
                    "event": "REM_SCHEDULED",
                    "event_id": event.id,
                    "chat_id": event.target_chat_id,
                    "starts_at": event.starts_at.isoformat(),
                }
            )
        )
        return event

    async def find_conflicts(
        self,
        *,
        creator_id: int,
        room: str,
        starts_at: datetime,
        event_id: str | None = None,
        tolerance_seconds: int = 60,
    ) -> list[Event]:
        draft = EventDraft(
            creator_id=creator_id,
            chat_id=None,
            thread_id=None,
            target_chat_id=None,
            title="",
            room=room,
            ticket="",
            starts_at=starts_at,
            lead_time_minutes=self._default_lead,
        )
        return await self._check_conflicts(draft, exclude_event_id=event_id, tolerance=timedelta(seconds=tolerance_seconds))

    async def get_event(self, event_id: str) -> Event | None:
        await self._ensure_cache()
        return self._events.get(event_id)

    async def list_events(
        self,
        *,
        chat_id: int | None = None,
        creator_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        tag: str | None = None,
        room: str | None = None,
        future_only: bool = True,
    ) -> list[Event]:
        await self._ensure_cache()
        results = [event for event in self._events.values() if not event.cancelled]
        if future_only:
            now = now_utc()
            results = [event for event in results if event.starts_at >= now]
        if chat_id is not None:
            results = [event for event in results if event.chat_id == chat_id or event.target_chat_id == chat_id]
        if creator_id is not None:
            results = [event for event in results if event.creator_id == creator_id]
        if date_from is not None:
            results = [event for event in results if event.starts_at >= date_from]
        if date_to is not None:
            results = [event for event in results if event.starts_at <= date_to]
        if tag is not None:
            results = [event for event in results if event.title.lower() == tag.lower()]
        if room is not None:
            results = [event for event in results if event.room.lower() == room.lower()]
        return sorted(results, key=lambda event: event.starts_at)

    async def cancel_event(self, event_id: str) -> bool:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return False
        event.cancelled = True
        await self._storage.save_all(self._events.values())
        logger.info("event_cancelled id=%s", event_id)
        audit_logger.info(json.dumps({"event": "REM_CANCELED", "event_id": event.id}))
        return True

    async def reschedule_event(
        self,
        event_id: str,
        new_time: datetime,
        *,
        allow_conflicts: bool = False,
    ) -> bool:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return False
        draft = self._make_draft(
            creator_id=event.creator_id,
            chat_id=event.chat_id,
            thread_id=event.thread_id,
            target_chat_id=event.target_chat_id,
            title=event.title,
            room=event.room,
            ticket=event.ticket,
            starts_at=new_time,
            lead_time_minutes=event.lead_time_minutes,
            repeat=event.repeat,
        )
        if not allow_conflicts:
            conflicts = await self._check_conflicts(draft, exclude_event_id=event_id)
            if conflicts:
                raise EventConflictError(draft, conflicts)
        event.starts_at = new_time
        event.last_fired_at = None
        await self._storage.save_all(self._events.values())
        logger.info("event_rescheduled id=%s new_time=%s", event_id, new_time.isoformat())
        audit_logger.info(
            json.dumps(
                {
                    "event": "REM_SCHEDULED",
                    "event_id": event.id,
                    "starts_at": event.starts_at.isoformat(),
                }
            )
        )
        return True

    async def change_room(
        self,
        event_id: str,
        new_room: str,
        *,
        allow_conflicts: bool = False,
    ) -> bool:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return False
        draft = self._make_draft(
            creator_id=event.creator_id,
            chat_id=event.chat_id,
            thread_id=event.thread_id,
            target_chat_id=event.target_chat_id,
            title=event.title,
            room=new_room,
            ticket=event.ticket,
            starts_at=event.starts_at,
            lead_time_minutes=event.lead_time_minutes,
            repeat=event.repeat,
        )
        if not allow_conflicts:
            conflicts = await self._check_conflicts(draft, exclude_event_id=event_id)
            if conflicts:
                raise EventConflictError(draft, conflicts)
        event.room = new_room
        await self._storage.save_all(self._events.values())
        logger.info("event_room_changed id=%s room=%s", event_id, new_room)
        return True

    async def set_repeat(self, event_id: str, repeat: str) -> bool:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return False
        event.repeat = repeat
        await self._storage.save_all(self._events.values())
        logger.info("event_repeat id=%s repeat=%s", event_id, repeat)
        return True

    async def snooze(self, event_id: str, minutes: int = 15, *, allow_conflicts: bool = False) -> bool:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return False
        new_time = event.starts_at + timedelta(minutes=minutes)
        return await self.reschedule_event(event_id, new_time, allow_conflicts=allow_conflicts)

    async def due_events(self) -> list[Event]:
        await self._ensure_cache()
        now = now_utc()
        due: list[Event] = []
        for event in self._events.values():
            if event.cancelled:
                continue
            remind_at = event.starts_at - timedelta(minutes=event.lead_time_minutes)
            if remind_at <= now and (event.last_fired_at is None or event.last_fired_at < remind_at):
                due.append(event)
        return due

    async def mark_fired(self, event_id: str) -> None:
        await self._ensure_cache()
        event = self._events.get(event_id)
        if not event:
            return
        now = now_utc()
        event.last_fired_at = now
        if event.repeat != "none":
            next_time = next_occurrence(event.starts_at, event.repeat)
            if next_time is not None:
                event.starts_at = next_time
                event.last_fired_at = None
                audit_logger.info(
                    json.dumps(
                        {
                            "event": "REM_SCHEDULED",
                            "event_id": event.id,
                            "starts_at": event.starts_at.isoformat(),
                        }
                    )
                )
        await self._storage.save_all(self._events.values())

    async def export_ics(
        self,
        *,
        tz: str,
        chat_id: int | None = None,
        creator_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        tag: str | None = None,
        room: str | None = None,
    ) -> bytes:
        events = await self.list_events(
            chat_id=chat_id,
            creator_id=creator_id,
            date_from=date_from,
            date_to=date_to,
            tag=tag,
            room=room,
            future_only=False,
        )
        now_stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//TelegramMeetingBot//EN",
            "CALSCALE:GREGORIAN",
        ]
        for event in events:
            local_start = to_local(event.starts_at, tz)
            local_end = local_start + self._default_duration
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{event.id}",
                    f"DTSTAMP:{now_stamp}",
                    f"DTSTART;TZID={tz}:{local_start.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID={tz}:{local_end.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{event.title} / {event.room}",
                    f"DESCRIPTION:Ticket {event.ticket}",
                    f"LOCATION:{event.room}",
                    "END:VEVENT",
                ]
            )
        lines.append("END:VCALENDAR")
        return "\n".join(lines).encode("utf-8")
