from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Dict, List

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..keyboards.inline import (
    conflict_resolution,
    conflict_room_menu,
    event_actions,
    events_pagination,
    freeze_keyboard,
)
from ..locales import get_text
from ..services.chats import ChatService
from ..services.events import EventConflictError, EventsService
from ..services.telegram import TelegramSender
from ..services.users import UserService
from ..utils.datetime import now_utc, to_local
from ..utils.parsing import parse_event

router = Router()
PAGE_SIZE = 5


class CreateEventState(StatesGroup):
    waiting_date = State()
    waiting_time = State()
    waiting_tag = State()
    waiting_room = State()
    waiting_ticket = State()
    conflict_room = State()


async def _safe_message(
    sender: TelegramSender,
    op: str,
    method,
    **kwargs,
):
    await sender.safe_tg_call("ui", op, method, **kwargs)


def _build_filters(text: str) -> Dict[str, str]:
    parts = text.split()
    filters: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", maxsplit=1)
            filters[key] = value
    return filters


async def _context_for(message: Message, users: UserService, chats: ChatService) -> dict:
    if message.chat.type == ChatType.PRIVATE:
        settings = await users.get(message.from_user.id)
        return {
            "language": settings.language,
            "timezone": settings.timezone,
            "lead_time": settings.lead_time_minutes,
            "target_chat_id": message.from_user.id if settings.direct_notifications else None,
            "chat_id": None,
            "thread_id": None,
            "is_admin": True,
        }
    title = message.chat.full_name or message.chat.title or str(message.chat.id)
    chat_settings = await chats.get_settings(message.chat.id, title=title)
    is_admin = await chats.is_admin(message.chat.id, message.from_user.id)
    target_chat_id = message.chat.id if chat_settings.registered else None
    return {
        "language": chat_settings.language,
        "timezone": chat_settings.timezone,
        "lead_time": chat_settings.lead_time_minutes,
        "target_chat_id": target_chat_id,
        "chat_id": message.chat.id,
        "thread_id": message.message_thread_id or chat_settings.message_thread_id,
        "is_admin": is_admin,
    }


async def _format_events(events, tz: str, language: str) -> str:
    if not events:
        return get_text(language, "no_events")
    lines = [get_text(language, "event_list_header")]
    for event in events:
        local_time = to_local(event.starts_at, tz)
        lines.append(
            f"• {local_time.strftime('%d.%m %H:%M')} — {event.title} / {event.room} / {event.ticket}"
        )
    return "\n".join(lines)


@router.message(Command("events"))
async def handle_events_list(
    message: Message,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    filters = _build_filters(message.text or "")
    context = await _context_for(message, users, chats)
    if message.chat.type == ChatType.PRIVATE:
        event_list = await events.list_events(creator_id=message.from_user.id)
    else:
        event_list = await events.list_events(chat_id=message.chat.id)
    event_list = _apply_filters(event_list, filters, context["timezone"])
    if not event_list:
        await _safe_message(
            telegram_sender,
            f"events:noitems:{message.chat.id}:{message.message_id}",
            message.answer,
            text=get_text(context["language"], "no_events"),
        )
        return
    await _send_events_page(
        telegram_sender,
        message,
        event_list,
        context["timezone"],
        context["language"],
        1,
    )


def _apply_filters(events_list, filters: Dict[str, str], tz: str):
    results = list(events_list)
    if "type" in filters:
        results = [event for event in results if event.title.lower() == filters["type"].lower()]
    if "room" in filters:
        results = [event for event in results if event.room.lower() == filters["room"].lower()]
    if "creator" in filters:
        try:
            creator_id = int(filters["creator"])
            results = [event for event in results if event.creator_id == creator_id]
        except ValueError:
            pass
    if "date" in filters:
        try:
            day, month = map(int, filters["date"].split("."))
        except ValueError:
            return results
        filtered = []
        for event in results:
            local = to_local(event.starts_at, tz)
            if local.day == day and local.month == month:
                filtered.append(event)
        results = filtered
    return results


async def _send_events_page(
    sender: TelegramSender,
    message: Message,
    event_list,
    tz: str,
    language: str,
    page: int,
) -> None:
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_events = event_list[start:end]
    total_pages = max(1, (len(event_list) + PAGE_SIZE - 1) // PAGE_SIZE)
    text = _format_events(page_events, tz, language)
    markup = events_pagination(page, total_pages, "events")
    await _safe_message(
        sender,
        f"events:list:{message.chat.id}:{message.message_id}:{page}",
        message.answer,
        text=text,
        reply_markup=markup,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("events:"))
async def handle_pagination_callback(
    callback: CallbackQuery,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    if not callback.message:
        return
    parts = callback.data.split(":")
    direction = parts[1]
    current_page = int(parts[2])
    context = await _context_for(callback.message, users, chats)
    if callback.message.chat.type == ChatType.PRIVATE:
        event_list = await events.list_events(creator_id=callback.from_user.id)
    else:
        event_list = await events.list_events(chat_id=callback.message.chat.id)
    event_list = _apply_filters(event_list, {}, context["timezone"])
    total_pages = max(1, (len(event_list) + PAGE_SIZE - 1) // PAGE_SIZE)
    if direction == "next" and current_page < total_pages:
        page = current_page + 1
    elif direction == "prev" and current_page > 1:
        page = current_page - 1
    else:
        page = current_page

    async def _edit() -> None:
        text = _format_events(
            event_list[(page - 1) * PAGE_SIZE : (page * PAGE_SIZE)],
            context["timezone"],
            context["language"],
        )
        try:
            await telegram_sender.safe_tg_call(
                "ui",
                f"events:edit:{callback.message.chat.id}:{callback.message.message_id}:{page}",
                callback.message.edit_text,
                text=text,
                reply_markup=events_pagination(page, total_pages, "events"),
            )
        except Exception:
            pass

    asyncio.create_task(_edit())


@router.message(Command("create"))
async def start_create_wizard(
    message: Message,
    state: FSMContext,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    context = await _context_for(message, users, chats)
    await state.clear()
    await state.update_data(context=context)
    await state.set_state(CreateEventState.waiting_date)
    await _safe_message(
        telegram_sender,
        f"create:date:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите дату (напр. 30.10, завтра, послезавтра)",
    )


@router.message(CreateEventState.waiting_date)
async def handle_date_step(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.update_data(date=message.text.strip())
    await state.set_state(CreateEventState.waiting_time)
    await _safe_message(
        telegram_sender,
        f"create:time:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите время (ЧЧ:ММ)",
    )


@router.message(CreateEventState.waiting_time)
async def handle_time_step(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.update_data(time=message.text.strip())
    await state.set_state(CreateEventState.waiting_tag)
    await _safe_message(
        telegram_sender,
        f"create:tag:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите тип встречи (тег)",
    )


@router.message(CreateEventState.waiting_tag)
async def handle_tag_step(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.update_data(tag=message.text.strip())
    await state.set_state(CreateEventState.waiting_room)
    await _safe_message(
        telegram_sender,
        f"create:room:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите переговорную",
    )


@router.message(CreateEventState.waiting_room)
async def handle_room_step(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.update_data(room=message.text.strip())
    await state.set_state(CreateEventState.waiting_ticket)
    await _safe_message(
        telegram_sender,
        f"create:ticket:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите номер заявки",
    )


@router.message(CreateEventState.waiting_ticket)
async def handle_ticket_step(
    message: Message,
    state: FSMContext,
    events: EventsService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    await state.clear()
    context = data.get("context", {})
    date = data.get("date", "")
    time_value = data.get("time", "")
    tag = data.get("tag", "")
    room = data.get("room", "")
    ticket = message.text.strip()
    tz = context.get("timezone", "UTC")
    text = f"{date} {tag} {time_value} {room} {ticket}"
    parsed = parse_event(text, tz)
    if not parsed:
        await _safe_message(
            telegram_sender,
            f"create:error:{message.chat.id}:{message.message_id}",
            message.answer,
            text=get_text(context.get("language", "ru"), "error_parse"),
        )
        return
    await _commit_event(
        message,
        telegram_sender,
        events,
        context,
        parsed,
    )


async def _commit_event(
    message: Message,
    sender: TelegramSender,
    events: EventsService,
    context: dict,
    parsed,
) -> None:
    try:
        event = await events.create_event(
            creator_id=message.from_user.id,
            chat_id=context.get("chat_id"),
            thread_id=context.get("thread_id"),
            target_chat_id=context.get("target_chat_id"),
            title=parsed.tag,
            room=parsed.room,
            ticket=parsed.ticket,
            starts_at=parsed.starts_at,
            lead_time_minutes=context.get("lead_time"),
        )
    except EventConflictError as conflict:
        await show_conflict(message, sender, events, context, conflict)
        return
    await _safe_message(
        sender,
        f"create:done:{message.chat.id}:{message.message_id}:{event.id}",
        message.answer,
        text=get_text(context.get("language", "ru"), "reminder_scheduled"),
        reply_markup=event_actions(event.id, context.get("is_admin", True)),
    )


async def show_conflict(
    message: Message,
    sender: TelegramSender,
    events: EventsService,
    context: dict,
    conflict: EventConflictError,
    *,
    mode: str = "create",
    extra_meta: dict | None = None,
) -> None:
    language = context.get("language", "ru")
    tz = context.get("timezone", "UTC")
    lines = [get_text(language, "conflict_detected")]
    rooms: List[str] = []
    for item in conflict.conflicts:
        local_time = to_local(item.starts_at, tz)
        rooms.append(item.room)
        lines.append(f"• {local_time.strftime('%d.%m %H:%M')} — {item.title} / {item.room}")
    lines.append(get_text(language, "conflict_options"))
    meta = {
        "language": language,
        "timezone": tz,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "rooms": sorted({room for room in rooms if room}),
        "is_admin": context.get("is_admin", True),
        "mode": mode,
    }
    if extra_meta:
        meta.update(extra_meta)
    draft_id = events.remember_draft(conflict.draft, meta=meta)
    await _safe_message(
        sender,
        f"conflict:notify:{message.chat.id}:{message.message_id}:{draft_id}",
        message.answer,
        text="\n".join(lines),
        reply_markup=conflict_resolution(draft_id),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("conflict:"))
async def handle_conflict_callbacks(
    callback: CallbackQuery,
    events: EventsService,
    telegram_sender: TelegramSender,
    state: FSMContext,
) -> None:
    if not callback.message:
        return
    parts = callback.data.split(":")
    action = parts[1]
    draft_id = parts[2]
    stored = events.get_draft(draft_id)
    if not stored:
        return
    draft, meta = stored
    language = meta.get("language", "ru")
    mode = meta.get("mode", "create")

    if action == "snooze":
        draft.starts_at += timedelta(minutes=15)
        try:
            if mode == "create":
                event = await events.create_event(
                    creator_id=draft.creator_id,
                    chat_id=draft.chat_id,
                    thread_id=draft.thread_id,
                    target_chat_id=draft.target_chat_id,
                    title=draft.title,
                    room=draft.room,
                    ticket=draft.ticket,
                    starts_at=draft.starts_at,
                    lead_time_minutes=draft.lead_time_minutes,
                )
            else:
                event_id = meta.get("event_id")
                if not event_id:
                    return
                await events.reschedule_event(event_id, draft.starts_at)
                event = await events.get_event(event_id)
        except EventConflictError as conflict:
            events.pop_draft(draft_id)
            await show_conflict(
                callback.message,
                telegram_sender,
                events,
                meta,
                conflict,
                mode=mode,
                extra_meta={"event_id": meta.get("event_id")},
            )
            return
        events.pop_draft(draft_id)
        markup = event_actions(event.id, meta.get("is_admin", True)) if event else None
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:resolved:{draft_id}",
            callback.message.edit_text,
            text=get_text(language, "reminder_scheduled"),
            reply_markup=markup,
        )
        return
    if action == "room":
        rooms = meta.get("rooms", [])
        if not rooms:
            rooms = ["7А", "7Б", "Переговорная 1"]
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:rooms:{draft_id}",
            callback.message.edit_text,
            text=get_text(language, "conflict_options"),
            reply_markup=conflict_room_menu(draft_id, rooms),
        )
        return
    if action == "setroom":
        room = parts[3]
        draft.room = room
        try:
            if mode == "create":
                event = await events.create_event(
                    creator_id=draft.creator_id,
                    chat_id=draft.chat_id,
                    thread_id=draft.thread_id,
                    target_chat_id=draft.target_chat_id,
                    title=draft.title,
                    room=draft.room,
                    ticket=draft.ticket,
                    starts_at=draft.starts_at,
                    lead_time_minutes=draft.lead_time_minutes,
                )
            else:
                event_id = meta.get("event_id")
                if not event_id:
                    return
                await events.change_room(event_id, draft.room)
                event = await events.get_event(event_id)
        except EventConflictError as conflict:
            events.pop_draft(draft_id)
            await show_conflict(
                callback.message,
                telegram_sender,
                events,
                meta,
                conflict,
                mode=mode,
                extra_meta={"event_id": meta.get("event_id")},
            )
            return
        events.pop_draft(draft_id)
        markup = event_actions(event.id, meta.get("is_admin", True)) if event else None
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:setroom:done:{draft_id}",
            callback.message.edit_text,
            text=get_text(language, "reminder_scheduled"),
            reply_markup=markup,
        )
        return
    if action == "manual":
        await state.set_state(CreateEventState.conflict_room)
        await state.update_data(draft_id=draft_id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:manual:{draft_id}",
            callback.message.edit_text,
            text="Введите новую переговорную",
            reply_markup=freeze_keyboard(callback.message.reply_markup or conflict_resolution(draft_id)),
        )
        return
    if action == "back":
        markup = conflict_resolution(draft_id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:back:{draft_id}",
            callback.message.edit_text,
            text=get_text(language, "conflict_options"),
            reply_markup=markup,
        )
        return
    if action == "cancel":
        events.pop_draft(draft_id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"conflict:cancel:{draft_id}",
            callback.message.edit_text,
            text=get_text(language, "reminder_cancelled"),
        )


@router.message(CreateEventState.conflict_room)
async def handle_conflict_room_manual(
    message: Message,
    state: FSMContext,
    events: EventsService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    await state.clear()
    draft_id = data.get("draft_id")
    if not draft_id:
        return
    stored = events.get_draft(draft_id)
    if not stored:
        return
    draft, meta = stored
    draft.room = message.text.strip()
    language = meta.get("language", "ru")
    mode = meta.get("mode", "create")
    try:
        if mode == "create":
            event = await events.create_event(
                creator_id=draft.creator_id,
                chat_id=draft.chat_id,
                thread_id=draft.thread_id,
                target_chat_id=draft.target_chat_id,
                title=draft.title,
                room=draft.room,
                ticket=draft.ticket,
                starts_at=draft.starts_at,
                lead_time_minutes=draft.lead_time_minutes,
            )
        else:
            event_id = meta.get("event_id")
            if not event_id:
                return
            await events.change_room(event_id, draft.room)
            event = await events.get_event(event_id)
    except EventConflictError as conflict:
        events.pop_draft(draft_id)
        await show_conflict(
            message,
            telegram_sender,
            events,
            meta,
            conflict,
            mode=mode,
            extra_meta={"event_id": meta.get("event_id")},
        )
        return
    events.pop_draft(draft_id)
    await _safe_message(
        telegram_sender,
        f"conflict:manual:done:{draft_id}",
        message.answer,
        text=get_text(language, "reminder_scheduled"),
        reply_markup=event_actions(event.id, meta.get("is_admin", True)) if event else None,
    )


@router.message(Command("export"))
async def handle_export(
    message: Message,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    context = await _context_for(message, users, chats)
    tz = context["timezone"]
    if message.chat.type == ChatType.PRIVATE:
        creator_id = message.from_user.id
        chat_id = None
    else:
        creator_id = None
        chat_id = message.chat.id
    ics = await events.export_ics(
        tz=tz,
        chat_id=chat_id,
        creator_id=creator_id,
    )
    filename = f"schedule_{now_utc().strftime('%Y%m%d')}.ics"
    document = BufferedInputFile(ics, filename)
    await telegram_sender.safe_tg_call(
        "heavy",
        f"export:{message.chat.id}:{message.message_id}",
        message.answer_document,
        document=document,
        caption=get_text(context["language"], "export_ready"),
    )


@router.message(Command("debug_seed"))
async def handle_debug_seed(
    message: Message,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    context = await _context_for(message, users, chats)
    now = now_utc()
    base = now + timedelta(minutes=10)
    for idx in range(3):
        await events.create_event(
            creator_id=message.from_user.id,
            chat_id=context.get("chat_id"),
            thread_id=context.get("thread_id"),
            target_chat_id=context.get("target_chat_id") or message.chat.id,
            title=f"Тест {idx + 1}",
            room=f"A{idx+1}",
            ticket=f"SEED-{idx+1}",
            starts_at=base + timedelta(minutes=30 * idx),
            lead_time_minutes=context.get("lead_time"),
            allow_conflicts=True,
        )
    await _safe_message(
        telegram_sender,
        f"seed:{message.chat.id}:{message.message_id}",
        message.answer,
        text=get_text(context["language"], "seed_done"),
    )


@router.message()
async def handle_new_event(
    message: Message,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    text = message.text or ""
    if not text.strip():
        return
    if message.text.startswith("/"):
        return
    context = await _context_for(message, users, chats)
    parsed = parse_event(text, context["timezone"])
    if not parsed:
        await _safe_message(
            telegram_sender,
            f"create:free:error:{message.chat.id}:{message.message_id}",
            message.reply if message.chat.type != ChatType.PRIVATE else message.answer,
            text=get_text(context["language"], "error_parse"),
        )
        return
    await _commit_event(message, telegram_sender, events, context, parsed)
