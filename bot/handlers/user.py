"""Handlers for user facing bot commands."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, Dispatcher, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.storage import Meeting, MeetingStorage, UserSettings
from bot.services.reminder import ReminderService
from bot.utils.meeting_parser import MeetingCommand, parse_meeting_command


@dataclass(slots=True)
class PendingCreation:
    token: str
    chat_id: int
    user_id: int
    command: MeetingCommand
    scheduled_at: datetime
    timezone: ZoneInfo
    created_at: datetime


@dataclass(slots=True)
class PendingReschedule:
    meeting_id: str
    chat_id: Optional[int]
    user_id: int
    context_token: str
    page: int
    message_id: Optional[int]
    message: Optional[types.Message]
    requested_at: datetime


@dataclass(slots=True)
class PendingSetting:
    kind: str
    user_id: int
    chat_id: Optional[int]
    requested_at: datetime


@dataclass(slots=True)
class MeetingListContext:
    token: str
    user_id: int
    chat_id: Optional[int]
    scope: str
    filters: Dict[str, str]
    created_at: datetime


class MeetingCreationCallback(CallbackData, prefix="mtgc"):
    token: str
    decision: str


class MeetingManageCallback(CallbackData, prefix="mtgm"):
    action: str
    meeting_id: str
    value: Optional[str] = None
    ctx: Optional[str] = None
    page: Optional[int] = None


class MeetingPaginationCallback(CallbackData, prefix="mtgp"):
    token: str
    page: int


class SettingsCallback(CallbackData, prefix="uset"):
    action: str
    value: Optional[str] = None


_PENDING_CREATIONS: Dict[str, PendingCreation] = {}
_PENDING_RESCHEDULE: Dict[Tuple[int, int], PendingReschedule] = {}
_PENDING_SETTINGS: Dict[Tuple[int, int], PendingSetting] = {}
_LIST_CONTEXTS: Dict[str, MeetingListContext] = {}

_PENDING_TTL = timedelta(minutes=10)
_LIST_TTL = timedelta(hours=1)
_PER_PAGE = 1

_BTN_CREATE = "➕ Создать встречу"
_BTN_MEETINGS = "📅 Мои встречи"
_BTN_SETTINGS = "⚙️ Настройки"

_MAIN_MENU = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[
        [types.KeyboardButton(text=_BTN_CREATE), types.KeyboardButton(text=_BTN_MEETINGS)],
        [types.KeyboardButton(text=_BTN_SETTINGS)],
    ],
)


def _now(storage: MeetingStorage) -> datetime:
    timezone = storage.timezone or ZoneInfo("UTC")
    return datetime.now(tz=timezone)


def _cleanup_pending(now: datetime) -> None:
    for token, pending in list(_PENDING_CREATIONS.items()):
        if now - pending.created_at > _PENDING_TTL:
            _PENDING_CREATIONS.pop(token, None)
    for key, pending in list(_PENDING_RESCHEDULE.items()):
        if now - pending.requested_at > _PENDING_TTL:
            _PENDING_RESCHEDULE.pop(key, None)
    for key, pending in list(_PENDING_SETTINGS.items()):
        if now - pending.requested_at > _PENDING_TTL:
            _PENDING_SETTINGS.pop(key, None)
    for token, context in list(_LIST_CONTEXTS.items()):
        if now - context.created_at > _LIST_TTL:
            _LIST_CONTEXTS.pop(token, None)


def _resolve_user_timezone(storage: MeetingStorage, settings: UserSettings) -> ZoneInfo:
    if settings.timezone:
        try:
            return ZoneInfo(settings.timezone)
        except ZoneInfoNotFoundError:
            pass
    if storage.timezone:
        return storage.timezone
    return ZoneInfo("UTC")


def _format_datetime_for_user(
    dt: datetime, settings: UserSettings, storage: MeetingStorage
) -> Tuple[str, datetime]:
    timezone = _resolve_user_timezone(storage, settings)
    aware = dt
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=storage.timezone or timezone)
    local_dt = aware.astimezone(timezone)
    formatted = local_dt.strftime(f"{settings.date_format} {settings.time_format}")
    return formatted, local_dt


def _render_meeting_card(
    meeting: Meeting, settings: UserSettings, storage: MeetingStorage
) -> str:
    when_text, _ = _format_datetime_for_user(meeting.scheduled_at, settings, storage)
    lines = [f"🗓 {when_text}"]
    if meeting.meeting_type:
        lines.append(f"🎯 {meeting.meeting_type}")
    elif meeting.title:
        lines.append(f"🎯 {meeting.title}")
    if meeting.room:
        lines.append(f"📍 Комната {meeting.room}")
    if meeting.request_number:
        lines.append(f"🆔 Заявка №{meeting.request_number}")
    if meeting.chat_id:
        chat = storage.get_chat(meeting.chat_id)
        chat_title = chat.title if chat and chat.title else str(meeting.chat_id)
        lines.append(f"💬 Чат: {chat_title}")
    lines.append(f"👤 Организатор: {meeting.organizer_id}")
    if meeting.participants:
        participants = ", ".join(str(pid) for pid in meeting.participants)
        lines.append(f"👥 Участники: {participants}")
    return "\n".join(lines)


def _format_filters(filters: Dict[str, str]) -> str:
    parts: List[str] = []
    if "date" in filters:
        parts.append(f"дата={filters['date']}")
    if "type" in filters:
        parts.append(f"тип={filters['type']}")
    if "room" in filters:
        parts.append(f"комната={filters['room']}")
    return ", ".join(parts)


def _parse_filter_args(raw: str) -> Dict[str, str]:
    filters: Dict[str, str] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"date", "дата"}:
            filters["date"] = value
        elif key in {"type", "тип"}:
            filters["type"] = value
        elif key in {"room", "комната"}:
            filters["room"] = value
    return filters


def _parse_date_filter(value: str, timezone: ZoneInfo) -> Optional[datetime.date]:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})$", value)
    if match:
        now = datetime.now(tz=timezone)
        day = int(match.group("day"))
        month = int(match.group("month"))
        try:
            return datetime(now.year, month, day).date()
        except ValueError:
            return None
    return None


def _meeting_local_date(
    meeting: Meeting, timezone: ZoneInfo, storage: MeetingStorage
) -> datetime.date:
    dt = meeting.scheduled_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=storage.timezone or timezone)
    return dt.astimezone(timezone).date()


def _apply_filters(
    meetings: Iterable[Meeting],
    filters: Dict[str, str],
    settings: UserSettings,
    storage: MeetingStorage,
) -> List[Meeting]:
    timezone = _resolve_user_timezone(storage, settings)
    now = _now(storage)
    filtered = [meeting for meeting in meetings if meeting.scheduled_at >= now]
    if "date" in filters:
        target = _parse_date_filter(filters["date"], timezone)
        if target is not None:
            filtered = [
                meeting
                for meeting in filtered
                if _meeting_local_date(meeting, timezone, storage) == target
            ]
    if "type" in filters:
        desired = filters["type"].strip().lower()
        filtered = [
            meeting
            for meeting in filtered
            if (meeting.meeting_type or meeting.title or "").strip().lower() == desired
        ]
    if "room" in filters:
        desired_room = filters["room"].strip().replace(" ", "").lower()
        filtered = [
            meeting
            for meeting in filtered
            if (meeting.room or "").replace(" ", "").lower() == desired_room
        ]
    return filtered


def _create_context(
    user_id: int,
    chat_id: Optional[int],
    scope: str,
    filters: Dict[str, str],
    now: datetime,
) -> MeetingListContext:
    token = uuid4().hex
    context = MeetingListContext(
        token=token,
        user_id=user_id,
        chat_id=chat_id,
        scope=scope,
        filters=dict(filters),
        created_at=now,
    )
    _LIST_CONTEXTS[token] = context
    return context


def _collect_meetings(
    storage: MeetingStorage,
    context: MeetingListContext,
    settings: UserSettings,
) -> List[Meeting]:
    if context.scope == "chat" and context.chat_id is not None:
        meetings = storage.list_meetings_for_chat(context.chat_id)
    else:
        meetings = storage.list_meetings_for_user(context.user_id, chat_id=context.chat_id)
    meetings = _apply_filters(meetings, context.filters, settings, storage)
    meetings.sort(key=lambda meeting: meeting.scheduled_at)
    return meetings


def _snooze_options(settings: UserSettings) -> List[int]:
    options = {5, 10, 15}
    if settings.default_lead_time and settings.default_lead_time % 60 == 0:
        minutes = settings.default_lead_time // 60
        if minutes:
            options.add(minutes)
    return sorted(options)


def _build_meeting_keyboard(
    meeting: Meeting,
    context: MeetingListContext,
    page: int,
    total_pages: int,
    can_manage: bool,
    settings: UserSettings,
    *,
    confirm_cancel: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_manage:
        snooze_buttons: List[InlineKeyboardButton] = []
        for minutes in _snooze_options(settings):
            snooze_buttons.append(
                InlineKeyboardButton(
                    text=f"⏰ Сноуз +{minutes}",
                    callback_data=MeetingManageCallback(
                        action="snooze",
                        meeting_id=meeting.id,
                        value=str(minutes),
                        ctx=context.token,
                        page=page,
                    ).pack(),
                )
            )
        if snooze_buttons:
            builder.row(*snooze_buttons)
        if confirm_cancel:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Да, отменяем",
                    callback_data=MeetingManageCallback(
                        action="cancel",
                        meeting_id=meeting.id,
                        value="confirm",
                        ctx=context.token,
                        page=page,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="↩️ Вернуться",
                    callback_data=MeetingManageCallback(
                        action="cancel",
                        meeting_id=meeting.id,
                        value="no",
                        ctx=context.token,
                        page=page,
                    ).pack(),
                ),
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=MeetingManageCallback(
                        action="reschedule",
                        meeting_id=meeting.id,
                        ctx=context.token,
                        page=page,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🗑️ Отменить",
                    callback_data=MeetingManageCallback(
                        action="cancel",
                        meeting_id=meeting.id,
                        ctx=context.token,
                        page=page,
                    ).pack(),
                ),
            )
    builder.row(
        InlineKeyboardButton(
            text="🔍 Фильтры",
            callback_data=MeetingManageCallback(
                action="filters",
                meeting_id=meeting.id,
                ctx=context.token,
                page=page,
            ).pack(),
        )
    )
    nav_buttons: List[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=MeetingPaginationCallback(token=context.token, page=page - 1).pack(),
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=MeetingPaginationCallback(token=context.token, page=page).pack(),
        )
    )
    if page + 1 < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=MeetingPaginationCallback(token=context.token, page=page + 1).pack(),
            )
        )
    builder.row(*nav_buttons)
    return builder.as_markup()

def _compose_page(
    storage: MeetingStorage,
    context: MeetingListContext,
    meetings: List[Meeting],
    page: int,
    settings: UserSettings,
    *,
    confirm_cancel_for: Optional[str] = None,
) -> Tuple[str, InlineKeyboardMarkup, int, int]:
    total_pages = max(1, math.ceil(len(meetings) / max(1, _PER_PAGE)))
    page = max(0, min(page, total_pages - 1))
    index = page * _PER_PAGE
    meeting = meetings[index]
    can_manage = _can_manage_meeting(storage, meeting, context.user_id)
    header: List[str] = []
    if context.scope == "chat":
        header.append("📅 Расписание чата")
    else:
        header.append("📅 Ваши встречи")
    if context.scope == "chat" and context.chat_id is not None:
        chat = storage.get_chat(context.chat_id)
        if chat and chat.title:
            header.append(f"💬 {chat.title}")
    filters_summary = _format_filters(context.filters)
    if filters_summary:
        header.append(f"🎛️ Фильтры: {filters_summary}")
    header.append(f"📖 Страница {page + 1} из {total_pages}")
    card_text = _render_meeting_card(meeting, settings, storage)
    text = "\n".join(header + ["", card_text])
    markup = _build_meeting_keyboard(
        meeting,
        context,
        page,
        total_pages,
        can_manage,
        settings,
        confirm_cancel=confirm_cancel_for == meeting.id,
    )
    return text, markup, page, total_pages


def _can_manage_meeting(storage: MeetingStorage, meeting: Meeting, user_id: int) -> bool:
    if meeting.organizer_id == user_id:
        return True
    if user_id in meeting.participants:
        return True
    if meeting.chat_id is not None and storage.has_chat_role(meeting.chat_id, user_id, ("admin",)):
        return True
    return False


def _render_empty_message(context: MeetingListContext) -> str:
    base = (
        "ℹ️ В этом чате пока нет предстоящих встреч."
        if context.scope == "chat"
        else "ℹ️ У вас нет предстоящих встреч."
    )
    if context.filters:
        return base + "\nПодправьте фильтры или создайте новую встречу кнопкой ➕."
    return base + "\nНажмите ➕, чтобы запланировать первую встречу."


def _parse_user_datetime_input(
    text: str,
    *,
    timezone: ZoneInfo,
    meeting: Meeting,
    storage: MeetingStorage,
) -> Optional[datetime]:
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone)
    match = re.match(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})$", text)
    if match:
        now = datetime.now(tz=timezone)
        day = int(match.group("day"))
        month = int(match.group("month"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        try:
            candidate = datetime(now.year, month, day, hour, minute, tzinfo=timezone)
        except ValueError:
            return None
        if candidate < now:
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:
                return None
        return candidate
    match = re.match(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$", text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if hour > 23 or minute > 59:
            return None
        reference = meeting.scheduled_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=storage.timezone or timezone)
        reference = reference.astimezone(timezone)
        candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < datetime.now(tz=timezone):
            candidate += timedelta(days=1)
        return candidate
    return None


def _render_settings_text(settings: UserSettings, storage: MeetingStorage) -> str:
    timezone = settings.timezone
    if not timezone:
        tz = storage.timezone
        timezone = getattr(tz, "key", str(tz)) if tz else "UTC"
    lead_text = (
        "🔕 Напоминания выключены"
        if settings.default_lead_time == 0
        else f"🔔 {ReminderService._format_lead_time(settings.default_lead_time)}"
    )
    return (
        "⚙️ Личные настройки\n"
        f"🌍 Часовой пояс: {timezone}\n"
        f"🗣️ Локаль: {settings.locale}\n"
        f"📅 Формат даты: {settings.date_format}\n"
        f"⏰ Формат времени: {settings.time_format}\n"
        f"⏳ Напоминание по умолчанию: {lead_text}"
    )


def _build_settings_keyboard(settings: UserSettings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌍 Часовой пояс",
            callback_data=SettingsCallback(action="timezone").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🇷🇺 DD.MM.YYYY",
            callback_data=SettingsCallback(action="locale", value="ru").pack(),
        ),
        InlineKeyboardButton(
            text="🇬🇧 YYYY-MM-DD",
            callback_data=SettingsCallback(action="locale", value="en").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⏰ +5 мин",
            callback_data=SettingsCallback(action="lead", value="300").pack(),
        ),
        InlineKeyboardButton(
            text="⏰ +10 мин",
            callback_data=SettingsCallback(action="lead", value="600").pack(),
        ),
        InlineKeyboardButton(
            text="⏰ +15 мин",
            callback_data=SettingsCallback(action="lead", value="900").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⏰ +30 мин",
            callback_data=SettingsCallback(action="lead", value="1800").pack(),
        ),
        InlineKeyboardButton(
            text="🔕 Без напоминаний",
            callback_data=SettingsCallback(action="lead", value="0").pack(),
        ),
    )
    return builder.as_markup()


def _settings_message_kwargs(storage: MeetingStorage, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    settings = storage.get_user_settings(user_id)
    text = _render_settings_text(settings, storage)
    markup = _build_settings_keyboard(settings)
    return text, markup

def create_router(storage: MeetingStorage, reminder: ReminderService) -> Router:
    router = Router(name="user-handlers")

    def _resolve_target_chat(
        message: types.Message, command_chat_id: Optional[int]
    ) -> Tuple[Optional[int], Optional[str]]:
        if message.chat and message.chat.type != "private":
            chat_id = message.chat.id
            if command_chat_id and command_chat_id != chat_id:
                return None, "⚠️ Укажите корректный чат через префикс #<id>."
            if not storage.is_chat_registered(chat_id):
                return None, "⚠️ Этот чат не зарегистрирован. Добавьте его через администратора."
            return chat_id, None
        chat_id = command_chat_id
        if chat_id is not None:
            if not storage.is_chat_registered(chat_id):
                return None, "⚠️ Укажите зарегистрированный чат для встреч или зарегистрируйте его."
            return chat_id, None
        if not message.from_user:
            return None, "⚠️ Не удалось определить вас. Попробуйте снова."
        available = storage.list_user_chats(message.from_user.id, roles=("admin", "user"))
        if not available:
            return None, "ℹ️ У вас нет доступных чатов. Укажите чат через #<id> или запросите доступ."
        if len(available) == 1:
            return available[0].id, None
        options = ", ".join(f"#{chat.id} — {chat.title or chat.id}" for chat in available)
        return None, f"ℹ️ Укажите чат через #<id>. Доступные чаты: {options}"

    async def _send_meeting_list(
        message: types.Message,
        *,
        scope: str,
        chat_id: Optional[int],
        filters: Dict[str, str],
    ) -> None:
        if not message.from_user:
            await message.answer(
                "⚠️ Не удалось определить вас. Попробуйте ещё раз или напишите мне в личном чате."
            )
            return
        now = _now(storage)
        _cleanup_pending(now)
        user_id = message.from_user.id
        settings = storage.get_user_settings(user_id)
        context = _create_context(user_id, chat_id, scope, filters, now)
        meetings = _collect_meetings(storage, context, settings)
        if not meetings:
            await message.answer(_render_empty_message(context))
            return
        text, markup, _, _ = _compose_page(storage, context, meetings, 0, settings)
        await message.answer(text, reply_markup=markup)
        context.created_at = now

    async def _refresh_context(
        *,
        context: MeetingListContext,
        page: int,
        settings: UserSettings,
        message: Optional[types.Message] = None,
        bot: Optional[Bot] = None,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        confirm_cancel_for: Optional[str] = None,
        target_meeting_id: Optional[str] = None,
    ) -> None:
        meetings = _collect_meetings(storage, context, settings)
        if not meetings:
            text = _render_empty_message(context)
            if message is not None:
                await message.edit_text(text)
            elif bot and chat_id is not None and message_id is not None:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            return
        if target_meeting_id:
            for idx, item in enumerate(meetings):
                if item.id == target_meeting_id:
                    page = idx // max(1, _PER_PAGE)
                    break
        text, markup, _, _ = _compose_page(
            storage,
            context,
            meetings,
            page,
            settings,
            confirm_cancel_for=confirm_cancel_for,
        )
        if message is not None:
            try:
                await message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest:
                await message.edit_reply_markup(reply_markup=markup)
        elif bot and chat_id is not None and message_id is not None:
            try:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            except TelegramBadRequest:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)
        context.created_at = _now(storage)

    async def _process_pending_setting(message: types.Message) -> bool:
        if not message.from_user:
            return False
        key = (message.from_user.id, message.chat.id if message.chat else 0)
        pending = _PENDING_SETTINGS.get(key)
        if not pending:
            return False
        text = (message.text or "").strip()
        if text.lower() in {"отмена", "cancel"}:
            _PENDING_SETTINGS.pop(key, None)
            await message.reply(
                "👌 Отменили изменение настроек. Можно выбрать действие заново в ⚙️ Настройки."
            )
            return True
        if pending.kind == "timezone":
            try:
                ZoneInfo(text)
            except ZoneInfoNotFoundError:
                await message.reply(
                    "😕 Не нашли такой часовой пояс. Укажите, например, Europe/Moscow."
                )
                return True
            storage.update_user_settings(message.from_user.id, timezone=text)
            _PENDING_SETTINGS.pop(key, None)
            await message.reply(f"✅ Часовой пояс обновлён на {text}.")
            return True
        return False

    async def _process_pending_reschedule(message: types.Message) -> bool:
        if not message.from_user:
            return False
        key = (message.from_user.id, message.chat.id if message.chat else 0)
        pending = _PENDING_RESCHEDULE.get(key)
        if not pending:
            return False
        text = (message.text or "").strip()
        if text.lower() in {"отмена", "cancel"}:
            _PENDING_RESCHEDULE.pop(key, None)
            await message.reply("👌 Оставили встречу без изменений.")
            return True
        meeting = storage.get_meeting(pending.meeting_id)
        if not meeting:
            _PENDING_RESCHEDULE.pop(key, None)
            await message.reply(
                "😕 Не нашли эту встречу. Обновите список и попробуйте снова."
            )
            return True
        settings = storage.get_user_settings(message.from_user.id)
        timezone = _resolve_user_timezone(storage, settings)
        new_time = _parse_user_datetime_input(text, timezone=timezone, meeting=meeting, storage=storage)
        if not new_time:
            await message.reply(
                "😕 Не получилось распознать дату и время. Попробуйте формат ДД.ММ ЧЧ:ММ или YYYY-MM-DD HH:MM."
            )
            return True
        updated = storage.update_meeting(meeting.id, scheduled_at=new_time)
        _PENDING_RESCHEDULE.pop(key, None)
        if not updated:
            await message.reply(
                "⚠️ Не удалось обновить встречу. Проверьте права доступа и повторите попытку."
            )
            return True
        await reminder.send_due_reminders()
        when_text, _ = _format_datetime_for_user(updated.scheduled_at, settings, storage)
        await message.reply(f"✅ Перенесли встречу на {when_text}.")
        context = _LIST_CONTEXTS.get(pending.context_token)
        if context:
            await _refresh_context(
                context=context,
                page=pending.page,
                settings=settings,
                message=pending.message,
                bot=message.bot,
                chat_id=pending.chat_id,
                message_id=pending.message_id,
                target_meeting_id=updated.id,
            )
        return True
    @router.message(CommandStart())
    async def handle_start(message: types.Message) -> None:
        _cleanup_pending(_now(storage))
        name = message.from_user.full_name if message.from_user else "друг"
        await message.answer(
            (
                "👋 Привет, {name}!\n\n"
                "Выбирайте действие на клавиатуре или используйте команды /help, /meetings, /schedule, /settings."
            ).format(name=name),
            reply_markup=_MAIN_MENU,
        )

    @router.message(Command("help"))
    async def handle_help(message: types.Message) -> None:
        await message.answer(
            "ℹ️ Что умею:\n"
            "• /meetings [фильтры] — показать ваши встречи\n"
            "• /schedule [фильтры] — расписание чата\n"
            "• /settings — настроить формат и напоминания\n\n"
            "Фильтры: ключ=значение, например date=2024-03-25 type=demo"
        )

    @router.message(Command("meetings"))
    async def handle_meetings(message: types.Message) -> None:
        if not message.from_user:
            await message.answer(
                "⚠️ Не удалось определить вас. Попробуйте повторить команду из личного чата."
            )
            return
        chat_id: Optional[int] = None
        if message.chat and message.chat.type != "private":
            chat_id = message.chat.id
            if not storage.has_chat_role(chat_id, message.from_user.id, ("admin", "user")):
                await message.answer(
                    "⛔ Нет доступа к встречам этого чата. Попросите администратора добавить вас."
                )
                return
        filters_text = ""
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                filters_text = parts[1]
        filters = _parse_filter_args(filters_text)
        await _send_meeting_list(message, scope="user", chat_id=chat_id, filters=filters)

    @router.message(Command("schedule"))
    async def handle_schedule(message: types.Message) -> None:
        if not message.chat:
            await message.answer("⚠️ Команда работает только в групповом чате. Откройте чат и повторите.")
            return
        if not message.from_user or not storage.has_chat_role(
            message.chat.id, message.from_user.id, ("admin", "user")
        ):
            await message.answer(
                "⛔ Нет доступа к расписанию этого чата. Попросите администратора выдать права."
            )
            return
        filters_text = ""
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                filters_text = parts[1]
        filters = _parse_filter_args(filters_text)
        await _send_meeting_list(message, scope="chat", chat_id=message.chat.id, filters=filters)

    @router.message(Command("settings"))
    async def handle_settings_command(message: types.Message) -> None:
        if not message.from_user:
            await message.answer(
                "⚠️ Не удалось определить вас. Попробуйте снова из личного чата."
            )
            return
        _cleanup_pending(_now(storage))
        text, markup = _settings_message_kwargs(storage, message.from_user.id)
        await message.answer(text, reply_markup=markup)
    @router.callback_query(MeetingCreationCallback.filter())
    async def handle_creation_callback(
        callback: types.CallbackQuery, callback_data: MeetingCreationCallback
    ) -> None:
        now = _now(storage)
        _cleanup_pending(now)
        pending = _PENDING_CREATIONS.get(callback_data.token)
        if not pending:
            await callback.answer("⌛ Запрос устарел. Начните создание заново.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        if not callback.from_user or callback.from_user.id != pending.user_id:
            await callback.answer("⛔ Эта кнопка вам недоступна.", show_alert=True)
            return
        if callback_data.decision == "cancel":
            _PENDING_CREATIONS.pop(callback_data.token, None)
            if callback.message:
                await callback.message.edit_text(
                    "❎ Создание встречи отменено. Используйте кнопку ➕, чтобы начать заново."
                )
            await callback.answer("👌 Отменили.")
            return
        if callback_data.decision != "confirm":
            await callback.answer()
            return
        await callback.answer("⏳ Создаём встречу…")
        command = pending.command
        if command.request_number:
            existing = storage.find_meeting_by_request_number(command.request_number)
            if existing:
                _PENDING_CREATIONS.pop(callback_data.token, None)
                if callback.message:
                    await callback.message.edit_text(
                        "⚠️ Встреча с таким номером заявки уже есть. Проверьте номер и попробуйте снова."
                    )
                await callback.answer("⚠️ Дубликат заявки.")
                return
        scheduled_at = pending.scheduled_at
        meeting_type = command.meeting_type or "Встреча"
        title = meeting_type if not command.room else f"{meeting_type} ({command.room})"
        meeting = storage.create_meeting(
            title=title,
            scheduled_at=scheduled_at,
            organizer_id=pending.user_id,
            meeting_type=command.meeting_type,
            room=command.room,
            request_number=command.request_number,
            participants=[pending.user_id],
            chat_id=pending.chat_id,
        )
        _PENDING_CREATIONS.pop(callback_data.token, None)
        await reminder.send_due_reminders()
        settings = storage.get_user_settings(pending.user_id)
        summary = _render_meeting_card(meeting, settings, storage)
        when_text, _ = _format_datetime_for_user(meeting.scheduled_at, settings, storage)
        summary_bits = [when_text]
        if meeting.meeting_type:
            summary_bits.append(meeting.meeting_type)
        if meeting.room:
            summary_bits.append(f"комната {meeting.room}")
        if meeting.request_number:
            summary_bits.append(f"№{meeting.request_number}")
        lead_seconds = settings.default_lead_time or 0
        if lead_seconds > 0:
            lead_hint = f"Напомним за {ReminderService._format_lead_time(lead_seconds)}."
        else:
            lead_hint = "Напоминания выключены — включите их в ⚙️ Настройки."
        created_text = f"✅ Встреча создана: {', '.join(summary_bits)}. {lead_hint}\n\n{summary}"
        if callback.message:
            await callback.message.edit_text(created_text)
        await callback.answer("✅ Запланировали!")

    @router.callback_query(MeetingPaginationCallback.filter())
    async def handle_pagination(
        callback: types.CallbackQuery, callback_data: MeetingPaginationCallback
    ) -> None:
        now = _now(storage)
        _cleanup_pending(now)
        context = _LIST_CONTEXTS.get(callback_data.token)
        if not context:
            await callback.answer("⌛ Список устарел. Запросите его снова командой или кнопкой.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        if not callback.from_user or callback.from_user.id != context.user_id:
            await callback.answer("⛔ Эта кнопка вам недоступна.", show_alert=True)
            return
        settings = storage.get_user_settings(context.user_id)
        await callback.answer("⏳ Листаем…")
        if callback.message:
            await _refresh_context(
                context=context,
                page=callback_data.page,
                settings=settings,
                message=callback.message,
            )
        await callback.answer("✅ Готово!")

    @router.callback_query(MeetingManageCallback.filter())
    async def handle_manage(
        callback: types.CallbackQuery, callback_data: MeetingManageCallback
    ) -> None:
        now = _now(storage)
        _cleanup_pending(now)
        context = _LIST_CONTEXTS.get(callback_data.ctx or "") if callback_data.ctx else None
        if not context:
            await callback.answer("⌛ Контекст устарел. Откройте список снова кнопкой или командой.", show_alert=True)
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        if not callback.from_user or callback.from_user.id != context.user_id:
            await callback.answer("⛔ Эта кнопка вам недоступна.", show_alert=True)
            return
        settings = storage.get_user_settings(context.user_id)
        meeting = storage.get_meeting(callback_data.meeting_id)
        page = callback_data.page or 0
        if callback_data.action == "filters":
            summary = _format_filters(context.filters)
            await callback.answer(summary or "🔍 Фильтры не заданы.")
            return
        if not meeting:
            await callback.answer("😕 Не нашли эту встречу. Обновите список.", show_alert=True)
            if callback.message:
                await _refresh_context(context=context, page=page, settings=settings, message=callback.message)
            return
        if not _can_manage_meeting(storage, meeting, callback.from_user.id):
            await callback.answer("⛔ Недостаточно прав. Обратитесь к организатору.", show_alert=True)
            return
        if callback_data.action == "snooze":
            try:
                minutes = int(callback_data.value or "0")
            except ValueError:
                minutes = 0
            if minutes <= 0:
                await callback.answer("⚠️ Некорректное значение.", show_alert=True)
                return
            await callback.answer("⏳ Сдвигаем напоминание…")
            new_time = meeting.scheduled_at + timedelta(minutes=minutes)
            updated = storage.update_meeting(meeting.id, scheduled_at=new_time)
            if not updated:
                await callback.answer("⚠️ Не удалось обновить встречу. Попробуйте позже.", show_alert=True)
                return
            await reminder.send_due_reminders()
            if callback.message:
                await _refresh_context(
                    context=context,
                    page=page,
                    settings=settings,
                    message=callback.message,
                    target_meeting_id=meeting.id,
                )
            await callback.answer(f"✅ Сдвинули на +{minutes} мин.")
            return
        if callback_data.action == "reschedule":
            key = (
                callback.from_user.id,
                callback.message.chat.id if callback.message and callback.message.chat else 0,
            )
            _PENDING_RESCHEDULE[key] = PendingReschedule(
                meeting_id=meeting.id,
                chat_id=callback.message.chat.id if callback.message else None,
                user_id=callback.from_user.id,
                context_token=context.token,
                page=page,
                message_id=callback.message.message_id if callback.message else None,
                message=callback.message,
                requested_at=now,
            )
            await callback.answer("📝 Отправьте новую дату и время сообщением.", show_alert=True)
            if callback.message:
                await callback.message.reply(
                    "✍️ Введите новую дату и время (ДД.ММ ЧЧ:ММ или YYYY-MM-DD HH:MM). Для отмены отправьте 'отмена'."
                )
            return
        if callback_data.action == "cancel":
            if callback_data.value == "confirm":
                await callback.answer("⏳ Отменяем встречу…")
                if not storage.cancel_meeting(meeting.id):
                    await callback.answer("⚠️ Не удалось отменить встречу.", show_alert=True)
                    return
                await reminder.send_due_reminders()
                if callback.message:
                    await _refresh_context(context=context, page=page, settings=settings, message=callback.message)
                await callback.answer("✅ Встреча отменена.")
                return
            if callback_data.value == "no":
                if callback.message:
                    await _refresh_context(context=context, page=page, settings=settings, message=callback.message)
                await callback.answer("👌 Оставили без изменений.")
                return
            if callback.message:
                await _refresh_context(
                    context=context,
                    page=page,
                    settings=settings,
                    message=callback.message,
                    confirm_cancel_for=meeting.id,
                )
            await callback.answer("❓ Подтвердите отмену.")
            return
        await callback.answer("✅ Готово!")

    @router.callback_query(SettingsCallback.filter())
    async def handle_settings_callback(
        callback: types.CallbackQuery, callback_data: SettingsCallback
    ) -> None:
        now = _now(storage)
        _cleanup_pending(now)
        if not callback.from_user:
            await callback.answer()
            return
        user_id = callback.from_user.id
        if callback_data.action == "timezone":
            key = (
                user_id,
                callback.message.chat.id if callback.message and callback.message.chat else 0,
            )
            _PENDING_SETTINGS[key] = PendingSetting(
                kind="timezone",
                user_id=user_id,
                chat_id=callback.message.chat.id if callback.message else None,
                requested_at=now,
            )
            await callback.answer(
                "📝 Отправьте название часового пояса сообщением, например Europe/Moscow.",
                show_alert=True,
            )
            if callback.message:
                await callback.message.reply(
                    "✍️ Введите новый часовой пояс (например Europe/Moscow). Для отмены отправьте 'отмена'."
                )
            return
        if callback_data.action == "locale":
            value = (callback_data.value or "").lower()
            if value == "ru":
                storage.update_user_settings(
                    user_id,
                    locale="ru_RU",
                    date_format="%d.%m.%Y",
                    time_format="%H:%M",
                )
                await callback.answer("✅ Форматы переключены на 🇷🇺.")
            elif value == "en":
                storage.update_user_settings(
                    user_id,
                    locale="en_US",
                    date_format="%Y-%m-%d",
                    time_format="%H:%M",
                )
                await callback.answer("✅ Formats switched to 🇬🇧.")
            else:
                await callback.answer("⚠️ Неизвестная локаль.", show_alert=True)
                return
        elif callback_data.action == "lead":
            try:
                seconds = int(callback_data.value or "0")
            except ValueError:
                await callback.answer("⚠️ Некорректное значение.", show_alert=True)
                return
            if seconds < 0:
                seconds = 0
            storage.update_user_settings(user_id, default_lead_time=seconds)
            if seconds == 0:
                await callback.answer("🔕 Напоминания отключены.")
            else:
                await callback.answer(f"🔔 Напомним за {ReminderService._format_lead_time(seconds)}.")
        else:
            await callback.answer("✅ Готово!")
            return
        if callback.message:
            text, markup = _settings_message_kwargs(storage, user_id)
            try:
                await callback.message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest:
                await callback.message.edit_reply_markup(reply_markup=markup)
    @router.message()
    async def handle_text(message: types.Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        if not message.from_user:
            return
        now = _now(storage)
        _cleanup_pending(now)
        if await _process_pending_setting(message):
            return
        if await _process_pending_reschedule(message):
            return
        text = message.text.strip()
        lowered = text.lower()
        if message.text == _BTN_CREATE or lowered == "создать встречу":
            await message.answer(
                "✍️ Отправьте строку: <дата> <тип> <время> <комната> <заявка>. Например: 25.03 DEMO 14:00 R101 12345"
            )
            return
        if message.text == _BTN_MEETINGS or lowered in {"список встреч", "мои встречи"}:
            chat_id = message.chat.id if message.chat and message.chat.type != "private" else None
            await _send_meeting_list(message, scope="user", chat_id=chat_id, filters={})
            return
        if message.text == _BTN_SETTINGS or lowered == "настройки":
            text, markup = _settings_message_kwargs(storage, message.from_user.id)
            await message.answer(text, reply_markup=markup)
            return
        command = parse_meeting_command(text, now)
        if not command:
            return
        chat_id, error = _resolve_target_chat(message, command.chat_id)
        if error:
            await message.answer(error)
            return
        if chat_id is None:
            return
        user_id = message.from_user.id
        if not storage.has_chat_role(chat_id, user_id, ("admin", "user")):
            await message.answer(
                "⛔ Нет прав для действий в этом чате. Попросите администратора выдать доступ."
            )
            return
        if command.action != "create":
            await message.answer(
                "ℹ️ Используйте кнопки карточки встречи для управления расписанием."
            )
            return
        if not command.scheduled_at:
            await message.answer(
                "⚠️ Не удалось определить дату и время. Уточните их и отправьте ещё раз."
            )
            return
        if command.request_number:
            existing = storage.find_meeting_by_request_number(command.request_number)
            if existing:
                await message.answer(
                    "⚠️ Встреча с таким номером заявки уже есть. Выберите другой номер."
                )
                return
        settings = storage.get_user_settings(user_id)
        timezone = _resolve_user_timezone(storage, settings)
        scheduled_at = command.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone)
        else:
            scheduled_at = scheduled_at.astimezone(timezone)
        pending = PendingCreation(
            token=uuid4().hex,
            chat_id=chat_id,
            user_id=user_id,
            command=command,
            scheduled_at=scheduled_at,
            timezone=timezone,
            created_at=now,
        )
        _PENDING_CREATIONS[pending.token] = pending
        preview = Meeting(
            id=pending.token,
            title=command.meeting_type or "Встреча",
            scheduled_at=scheduled_at,
            organizer_id=user_id,
            participants=[user_id],
            meeting_type=command.meeting_type,
            room=command.room,
            request_number=command.request_number,
            chat_id=chat_id,
        )
        summary = _render_meeting_card(preview, settings, storage)
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(
                text="✅ Запланировать",
                callback_data=MeetingCreationCallback(token=pending.token, decision="confirm").pack(),
            ),
            InlineKeyboardButton(
                text="🗑️ Отменить",
                callback_data=MeetingCreationCallback(token=pending.token, decision="cancel").pack(),
            ),
        )
        await message.answer(
            "Создать встречу?\n\n" + summary,
            reply_markup=keyboard.as_markup(),
        )

    return router


def register(dispatcher: Dispatcher, storage: MeetingStorage, reminder: ReminderService) -> None:
    """Register router within provided dispatcher."""

    dispatcher.include_router(create_router(storage, reminder))
