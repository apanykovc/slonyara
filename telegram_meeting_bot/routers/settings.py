from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..keyboards.inline import freeze_keyboard, settings_menu
from ..locales import get_text
from ..services.chats import ChatService
from ..services.telegram import TelegramSender
from ..services.users import UserService

router = Router()


class SettingsState(StatesGroup):
    waiting_lead = State()
    waiting_timezone = State()
    waiting_quiet = State()
    waiting_language = State()


async def _send(sender: TelegramSender, op: str, method, **kwargs) -> None:
    await sender.safe_tg_call("ui", op, method, **kwargs)


@router.message(Command("settings"))
async def handle_settings(
    message: Message,
    users: UserService,
    chats: ChatService,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    await state.clear()
    if message.chat.type == ChatType.PRIVATE:
        settings = await users.get(message.from_user.id)
        language = settings.language
        lead = settings.lead_time_minutes
        tz = settings.timezone
        quiet = (settings.quiet_hours_start, settings.quiet_hours_end)
    else:
        title = message.chat.full_name or message.chat.title or str(message.chat.id)
        settings = await chats.get_settings(message.chat.id, title=title)
        language = settings.language
        lead = settings.lead_time_minutes
        tz = settings.timezone
        quiet = (settings.quiet_hours_start, settings.quiet_hours_end)
    quiet_text = f"{quiet[0]}-{quiet[1]}" if all(v is not None for v in quiet) else "—"
    text = (
        f"Lead: {lead} мин\n"
        f"TZ: {tz}\n"
        f"Quiet: {quiet_text}\n"
        f"Lang: {language}"
    )
    include_registration = message.chat.type != ChatType.PRIVATE
    await _send(
        telegram_sender,
        f"settings:show:{message.chat.id}:{message.message_id}",
        message.answer,
        text=text,
        reply_markup=settings_menu(language, include_registration),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("settings:"))
async def handle_settings_callback(
    callback: CallbackQuery,
    users: UserService,
    chats: ChatService,
    state: FSMContext,
    telegram_sender: TelegramSender,
) -> None:
    if not callback.message:
        return
    action = callback.data.split(":", maxsplit=1)[1]
    include_registration = callback.message.chat.type != ChatType.PRIVATE
    if callback.message.chat.type == ChatType.PRIVATE:
        settings = await users.get(callback.from_user.id)
        language = settings.language
        scope = "user"
    else:
        title = callback.message.chat.full_name or callback.message.chat.title or str(callback.message.chat.id)
        settings = await chats.get_settings(callback.message.chat.id, title=title)
        language = settings.language
        scope = "chat"
    await state.update_data(scope=scope)
    if callback.message.reply_markup:
        await _send(
            telegram_sender,
            f"settings:freeze:{callback.message.chat.id}:{callback.message.message_id}",
            callback.message.edit_reply_markup,
            reply_markup=freeze_keyboard(callback.message.reply_markup),
        )
    if action == "lead":
        await _send(
            telegram_sender,
            f"settings:lead_prompt:{callback.message.chat.id}",
            callback.message.answer,
            text="Введите новое значение lead-time в минутах",
        )
        await state.set_state(SettingsState.waiting_lead)
    elif action == "tz":
        await _send(
            telegram_sender,
            f"settings:tz_prompt:{callback.message.chat.id}",
            callback.message.answer,
            text="Введите таймзону, например Europe/Moscow",
        )
        await state.set_state(SettingsState.waiting_timezone)
    elif action == "quiet":
        await _send(
            telegram_sender,
            f"settings:quiet_prompt:{callback.message.chat.id}",
            callback.message.answer,
            text="Введите тихие часы в формате HH-HH или 0-0 для отключения",
        )
        await state.set_state(SettingsState.waiting_quiet)
    elif action == "lang":
        await _send(
            telegram_sender,
            f"settings:lang_prompt:{callback.message.chat.id}",
            callback.message.answer,
            text="Введите язык: ru или en",
        )
        await state.set_state(SettingsState.waiting_language)
    elif action == "register" and scope == "chat":
        title = callback.message.chat.full_name or callback.message.chat.title or str(callback.message.chat.id)
        chat_settings = await chats.get_settings(callback.message.chat.id, title=title)
        chat_settings.registered = not chat_settings.registered
        await chats.update_settings(chat_settings)
        text = (
            "Chat registered." if chat_settings.registered else "Chat unregistered."
        ) if language == "en" else (
            "Чат зарегистрирован." if chat_settings.registered else "Чат отвязан."
        )
        await _send(
            telegram_sender,
            f"settings:register_toggle:{callback.message.chat.id}",
            callback.message.answer,
            text=text,
        )
    else:
        await _send(
            telegram_sender,
            f"settings:help:{callback.message.chat.id}",
            callback.message.answer,
            text=get_text(language, "help"),
        )
    await _send(
        telegram_sender,
        f"settings:menu:{callback.message.chat.id}",
        callback.message.edit_reply_markup,
        reply_markup=settings_menu(language, include_registration),
    )


@router.message(SettingsState.waiting_lead)
async def process_lead(
    message: Message,
    state: FSMContext,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    scope = data.get("scope")
    try:
        value = int(message.text.strip())
    except (ValueError, AttributeError):
        await _send(
            telegram_sender,
            f"settings:lead:error:{message.chat.id}",
            message.answer,
            text="Введите число",
        )
        return
    if scope == "user":
        settings = await users.get(message.from_user.id)
        settings.lead_time_minutes = value
        await users.update(settings)
        language = settings.language
    else:
        title = message.chat.full_name or message.chat.title or str(message.chat.id)
        settings = await chats.get_settings(message.chat.id, title=title)
        settings.lead_time_minutes = value
        await chats.update_settings(settings)
        language = settings.language
    await _send(
        telegram_sender,
        f"settings:lead:ok:{message.chat.id}",
        message.answer,
        text=get_text(language, "settings_saved"),
    )
    await state.clear()


@router.message(SettingsState.waiting_timezone)
async def process_timezone(
    message: Message,
    state: FSMContext,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    scope = data.get("scope")
    tz = message.text.strip()
    if scope == "user":
        settings = await users.get(message.from_user.id)
        settings.timezone = tz
        await users.update(settings)
        language = settings.language
    else:
        title = message.chat.full_name or message.chat.title or str(message.chat.id)
        settings = await chats.get_settings(message.chat.id, title=title)
        settings.timezone = tz
        await chats.update_settings(settings)
        language = settings.language
    await _send(
        telegram_sender,
        f"settings:tz:ok:{message.chat.id}",
        message.answer,
        text=get_text(language, "settings_saved"),
    )
    await state.clear()


@router.message(SettingsState.waiting_quiet)
async def process_quiet(
    message: Message,
    state: FSMContext,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    scope = data.get("scope")
    text_value = message.text.strip()
    try:
        start_str, end_str = text_value.split("-", maxsplit=1)
        start = int(start_str)
        end = int(end_str)
    except (ValueError, AttributeError):
        await _send(
            telegram_sender,
            f"settings:quiet:error:{message.chat.id}",
            message.answer,
            text="Введите в формате HH-HH",
        )
        return
    if scope == "user":
        settings = await users.get(message.from_user.id)
        settings.quiet_hours_start = start
        settings.quiet_hours_end = end
        await users.update(settings)
        language = settings.language
    else:
        title = message.chat.full_name or message.chat.title or str(message.chat.id)
        settings = await chats.get_settings(message.chat.id, title=title)
        settings.quiet_hours_start = start
        settings.quiet_hours_end = end
        await chats.update_settings(settings)
        language = settings.language
    await _send(
        telegram_sender,
        f"settings:quiet:ok:{message.chat.id}",
        message.answer,
        text=get_text(language, "settings_saved"),
    )
    await state.clear()


@router.message(SettingsState.waiting_language)
async def process_language(
    message: Message,
    state: FSMContext,
    users: UserService,
    chats: ChatService,
    telegram_sender: TelegramSender,
) -> None:
    data = await state.get_data()
    scope = data.get("scope")
    value = message.text.strip().lower()
    if value not in {"ru", "en"}:
        await _send(
            telegram_sender,
            f"settings:lang:error:{message.chat.id}",
            message.answer,
            text="Введите ru или en",
        )
        return
    if scope == "user":
        settings = await users.get(message.from_user.id)
        settings.language = value
        await users.update(settings)
        language = value
    else:
        title = message.chat.full_name or message.chat.title or str(message.chat.id)
        settings = await chats.get_settings(message.chat.id, title=title)
        settings.language = value
        await chats.update_settings(settings)
        language = value
    await _send(
        telegram_sender,
        f"settings:lang:ok:{message.chat.id}",
        message.answer,
        text=get_text(language, "settings_saved"),
    )
    await state.clear()
