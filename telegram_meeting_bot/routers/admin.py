from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..keyboards.inline import admin_menu, event_actions
from ..locales import get_text
from ..models.chat import ChatRole, ChatSettings
from ..models.event import Event
from ..models.user import UserSettings
from ..services.chats import ChatService
from ..services.events import EventConflictError, EventsService
from ..services.telegram import TelegramSender
from ..services.users import UserService
from ..storage.base import JsonStorage, SQLiteStorage
from ..utils.datetime import aware_from_naive, to_local
from ..utils.metrics import MetricsCollector
from .events import show_conflict

router = Router()


class AdminState(StatesGroup):
    waiting_move = State()
    register_timezone = State()
    register_lead = State()
    register_thread = State()
    grant_admin = State()
    revoke_admin = State()


async def _is_admin(chats: ChatService, chat_id: int, user_id: int) -> bool:
    admins = await chats.list_admins(chat_id)
    return not admins or user_id in admins


async def _event_context(
    event,
    users: UserService,
    chats: ChatService,
    actor_id: int,
) -> dict:
    if event.chat_id:
        settings = await chats.get_settings(event.chat_id)
        language = settings.language
        tz = settings.timezone
        actor_is_admin = await chats.is_admin(event.chat_id, actor_id)
        creator_admin = await chats.is_admin(event.chat_id, event.creator_id)
        return {
            "language": language,
            "timezone": tz,
            "is_admin": actor_is_admin,
            "creator_is_admin": creator_admin,
        }
    settings = await users.get(event.creator_id)
    return {
        "language": settings.language,
        "timezone": settings.timezone,
        "is_admin": True,
        "creator_is_admin": True,
    }


def _can_manage(event, user_id: int, context: dict) -> bool:
    if event.creator_id == user_id:
        return True
    return context.get("is_admin", False)


@router.callback_query(lambda c: c.data and c.data.startswith("event:"))
async def handle_event_callback(
    callback: CallbackQuery,
    events: EventsService,
    chats: ChatService,
    users: UserService,
    telegram_sender: TelegramSender,
    state: FSMContext,
) -> None:
    if not callback.message:
        return
    parts = callback.data.split(":")
    action = parts[1]
    if action == "repeat":
        repeat = parts[2]
        event_id = parts[3]
    else:
        event_id = parts[2]
        repeat = None
    event = await events.get_event(event_id)
    if not event:
        return
    context = await _event_context(event, users, chats, callback.from_user.id)
    language = context.get("language", "ru")

    if action in {"move", "cancel", "repeat"} and not context.get("is_admin", False):
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:denied:{event_id}",
            callback.message.answer,
            text=get_text(language, "permission_denied"),
        )
        return

    if action == "snooze":
        if not _can_manage(event, callback.from_user.id, context):
            await telegram_sender.safe_tg_call(
                "ui",
                f"event:denied:snooze:{event_id}",
                callback.message.answer,
                text=get_text(language, "permission_denied"),
            )
            return
        try:
            await events.snooze(event_id)
            updated = await events.get_event(event_id)
        except EventConflictError as conflict:
            meta = {"language": language, "timezone": context.get("timezone", "UTC"), "is_admin": context.get("is_admin", True), "mode": "update", "event_id": event_id}
            await show_conflict(callback.message, telegram_sender, events, meta, conflict, mode="update", extra_meta={"event_id": event_id})
            return
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:snoozed:{event_id}",
            callback.message.answer,
            text=get_text(language, "reminder_scheduled"),
            reply_markup=event_actions(updated.id if updated else event_id, context.get("is_admin", True)),
        )
        return
    if action == "cancel":
        await events.cancel_event(event_id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:cancel:{event_id}",
            callback.message.answer,
            text=get_text(language, "reminder_cancelled"),
        )
        return
    if action == "move":
        await state.set_state(AdminState.waiting_move)
        await state.update_data(event_id=event_id, context=context)
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:move:{event_id}",
            callback.message.answer,
            text="Введите новую дату и время (формат 30.10 10:00)",
        )
        return
    if action == "repeat" and repeat:
        await events.set_repeat(event_id, repeat)
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:repeat:{event_id}:{repeat}",
            callback.message.answer,
            text="Повтор обновлён",
        )
        return


@router.message(AdminState.waiting_move)
async def handle_move_input(
    message: Message,
    state: FSMContext,
    events: EventsService,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    await state.clear()
    event_id = data.get("event_id")
    context = data.get("context", {})
    event = await events.get_event(event_id)
    if not event:
        return
    language = context.get("language", "ru")
    tz = context.get("timezone", "UTC")
    try:
        date_str, time_str = message.text.strip().split()
        day, month = map(int, date_str.split("."))
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        await telegram_sender.safe_tg_call(
            "ui",
            f"event:move:format:{event_id}",
            message.answer,
            text="Используйте формат 30.10 10:00",
        )
        return
    base_local = to_local(event.starts_at, tz)
    year = base_local.year
    new_dt = datetime(year, month, day, hour, minute)
    new_time = aware_from_naive(new_dt, tz)
    try:
        await events.reschedule_event(event_id, new_time)
    except EventConflictError as conflict:
        meta = {"language": language, "timezone": tz, "is_admin": context.get("is_admin", True), "mode": "update", "event_id": event_id}
        await show_conflict(message, telegram_sender, events, meta, conflict, mode="update", extra_meta={"event_id": event_id})
        return
    await telegram_sender.safe_tg_call(
        "ui",
        f"event:moved:{event_id}",
        message.answer,
        text=get_text(language, "reminder_scheduled"),
    )


@router.message(Command("admin"))
async def handle_admin_menu(
    message: Message,
    chats: ChatService,
    telegram_sender: TelegramSender,
    users: UserService,
) -> None:
    if message.chat.type == ChatType.PRIVATE:
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:private:{message.from_user.id}",
            message.answer,
            text="Команда доступна в групповом чате",
        )
        return
    if not await _is_admin(chats, message.chat.id, message.from_user.id):
        settings = await chats.get_settings(message.chat.id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:denied:{message.chat.id}:{message.from_user.id}",
            message.answer,
            text=get_text(settings.language, "permission_denied"),
        )
        return
    settings = await chats.get_settings(message.chat.id)
    markup = admin_menu(include_roles=True, include_registration=True, language=settings.language)
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:menu:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Администрирование",
        reply_markup=markup,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("admin:"))
async def handle_admin_callbacks(
    callback: CallbackQuery,
    chats: ChatService,
    users: UserService,
    telegram_sender: TelegramSender,
    state: FSMContext,
    config: Config,
    metrics: MetricsCollector,
) -> None:
    if not callback.message:
        return
    action = callback.data.split(":")[1]
    if callback.message.chat.type == ChatType.PRIVATE:
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:privatecb:{callback.from_user.id}",
            callback.message.answer,
            text="Команда доступна в группе",
        )
        return
    if not await _is_admin(chats, callback.message.chat.id, callback.from_user.id):
        settings = await chats.get_settings(callback.message.chat.id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:deniedcb:{callback.message.chat.id}:{callback.from_user.id}",
            callback.message.answer,
            text=get_text(settings.language, "permission_denied"),
        )
        return
    settings = await chats.get_settings(callback.message.chat.id)
    language = settings.language
    if action == "register":
        await state.set_state(AdminState.register_timezone)
        await state.update_data(chat_id=callback.message.chat.id, title=settings.title)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:register:{callback.message.chat.id}",
            callback.message.answer,
            text="Введите часовой пояс (например Europe/Moscow)",
        )
        return
    if action == "grant":
        await state.set_state(AdminState.grant_admin)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:grant:{callback.message.chat.id}",
            callback.message.answer,
            text="Укажите user_id пользователя",
        )
        return
    if action == "revoke":
        await state.set_state(AdminState.revoke_admin)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:revoke:{callback.message.chat.id}",
            callback.message.answer,
            text="Укажите user_id для снятия роли",
        )
        return
    if action == "status":
        stats = await metrics.status_report()
        text = get_text(
            language,
            "status_template",
            queue=stats["queue_size"],
            sends=stats["sends"],
            retries5=stats["retries_5m"],
            retries60=stats["retries_60m"],
            timeouts5=stats["timeouts_5m"],
            timeouts60=stats["timeouts_60m"],
            p50_5=stats["latency_p50_5m"],
            p95_5=stats["latency_p95_5m"],
            p50_60=stats["latency_p50_60m"],
            p95_60=stats["latency_p95_60m"],
            tasks=len(asyncio.all_tasks()),
        )
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:status:{callback.message.chat.id}",
            callback.message.answer,
            text=text,
        )
        return
    if action == "migrate":
        await _handle_migrate(callback.message, telegram_sender, config, language)


@router.message(AdminState.register_timezone)
async def handle_register_timezone(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.update_data(timezone=message.text.strip())
    await state.set_state(AdminState.register_lead)
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:lead:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Введите lead-time в минутах",
    )


@router.message(AdminState.register_lead)
async def handle_register_lead(
    message: Message,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    try:
        lead = int(message.text.strip())
    except ValueError:
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:leaderr:{message.chat.id}:{message.message_id}",
            message.answer,
            text="Введите число",
        )
        return
    await state.update_data(lead=lead)
    await state.set_state(AdminState.register_thread)
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:thread:{message.chat.id}:{message.message_id}",
        message.answer,
        text="Укажите message_thread_id или напишите skip",
    )


@router.message(AdminState.register_thread)
async def handle_register_thread(
    message: Message,
    state: FSMContext,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    await state.clear()
    chat_id = data.get("chat_id", message.chat.id)
    title = data.get("title", str(chat_id))
    timezone_value = data.get("timezone", "UTC")
    lead = data.get("lead", 30)
    text_value = message.text.strip().lower()
    thread_id = None
    if text_value != "skip":
        try:
            thread_id = int(text_value)
        except ValueError:
            thread_id = message.message_thread_id
    await chats.register_chat(
        chat_id=chat_id,
        title=title,
        timezone=timezone_value,
        lead_time=lead,
        thread_id=thread_id,
    )
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:registered:{chat_id}",
        message.answer,
        text="Чат зарегистрирован",
    )


@router.message(AdminState.grant_admin)
async def handle_grant_admin(
    message: Message,
    state: FSMContext,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    await state.clear()
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:grant:err:{message.chat.id}",
            message.answer,
            text="Введите числовой user_id",
        )
        return
    await chats.set_role(message.chat.id, user_id, "admin")
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:grant:ok:{message.chat.id}:{user_id}",
        message.answer,
        text="Администратор назначен",
    )


@router.message(AdminState.revoke_admin)
async def handle_revoke_admin(
    message: Message,
    state: FSMContext,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    await state.clear()
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:revoke:err:{message.chat.id}",
            message.answer,
            text="Введите числовой user_id",
        )
        return
    await chats.set_role(message.chat.id, user_id, "user")
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:revoke:ok:{message.chat.id}:{user_id}",
        message.answer,
        text="Роль снята",
    )


async def _handle_migrate(message: Message, sender: TelegramSender, config: Config, language: str) -> None:
    if config.bot.storage_backend != "sqlite":
        await sender.safe_tg_call(
            "ui",
            f"admin:migrate:disabled:{message.chat.id}",
            message.answer,
            text="SQLite backend не активирован",
        )
        return
    base_dir = config.bot.data_dir
    sqlite_path = config.bot.sqlite_path or base_dir / "bot.db"
    sqlite_events = SQLiteStorage(sqlite_path, "events", Event, "id")
    sqlite_users = SQLiteStorage(sqlite_path, "users", UserSettings, "user_id")
    sqlite_chats = SQLiteStorage(sqlite_path, "chats", ChatSettings, "chat_id")
    sqlite_roles = SQLiteStorage(
        sqlite_path,
        "roles",
        ChatRole,
        "role",
        key_getter=lambda data: f"{data['chat_id']}:{data['user_id']}",
    )
    await _copy_json_to_sqlite(base_dir / "events.json", sqlite_events, Event)
    await _copy_json_to_sqlite(base_dir / "users.json", sqlite_users, UserSettings)
    await _copy_json_to_sqlite(base_dir / "chats.json", sqlite_chats, ChatSettings)
    await _copy_json_to_sqlite(base_dir / "roles.json", sqlite_roles, ChatRole)
    await sender.safe_tg_call(
        "ui",
        f"admin:migrate:done:{message.chat.id}",
        message.answer,
        text="Миграция завершена",
    )


async def _copy_json_to_sqlite(path: Path, storage: SQLiteStorage, model) -> None:
    json_storage = JsonStorage(path, model)
    backup = path.with_suffix(".bak")
    if path.exists():
        shutil.copy2(path, backup)
    items = await json_storage.load_all()
    if items:
        await storage.save_all(items)


@router.message(Command("status"))
async def handle_status_command(
    message: Message,
    chats: ChatService,
    telegram_sender: TelegramSender,
    metrics: MetricsCollector,
) -> None:
    if message.chat.type != ChatType.PRIVATE and not await _is_admin(chats, message.chat.id, message.from_user.id):
        settings = await chats.get_settings(message.chat.id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:status:denied:{message.chat.id}",
            message.answer,
            text=get_text(settings.language, "permission_denied"),
        )
        return
    language = "ru"
    if message.chat.type != ChatType.PRIVATE:
        settings = await chats.get_settings(message.chat.id)
        language = settings.language
    stats = await metrics.status_report()
    text = get_text(
        language,
        "status_template",
        queue=stats["queue_size"],
        sends=stats["sends"],
        retries5=stats["retries_5m"],
        retries60=stats["retries_60m"],
        timeouts5=stats["timeouts_5m"],
        timeouts60=stats["timeouts_60m"],
        p50_5=stats["latency_p50_5m"],
        p95_5=stats["latency_p95_5m"],
        p50_60=stats["latency_p50_60m"],
        p95_60=stats["latency_p95_60m"],
        tasks=len(asyncio.all_tasks()),
    )
    await telegram_sender.safe_tg_call(
        "ui",
        f"admin:status:cmd:{message.chat.id}",
        message.answer,
        text=text,
    )


@router.message(Command("migrate"))
async def handle_migrate_command(
    message: Message,
    chats: ChatService,
    telegram_sender: TelegramSender,
    config: Config,
) -> None:
    if message.chat.type != ChatType.PRIVATE and not await _is_admin(chats, message.chat.id, message.from_user.id):
        settings = await chats.get_settings(message.chat.id)
        await telegram_sender.safe_tg_call(
            "ui",
            f"admin:migrate:denied:{message.chat.id}",
            message.answer,
            text=get_text(settings.language, "permission_denied"),
        )
        return
    language = "ru"
    if message.chat.type != ChatType.PRIVATE:
        settings = await chats.get_settings(message.chat.id)
        language = settings.language
    await _handle_migrate(message, telegram_sender, config, language)
