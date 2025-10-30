from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..keyboards.inline import main_menu
from ..locales import get_text
from ..services.chats import ChatService
from ..services.events import EventsService
from ..services.users import UserService
from ..utils.datetime import to_local
from ..services.telegram import TelegramSender

router = Router()


async def _send_menu(message: Message, language: str, sender: TelegramSender) -> None:
    await sender.safe_tg_call(
        "ui",
        f"menu:answer:{message.chat.id}:{message.message_id}",
        message.answer,
        get_text(language, "start"),
        reply_markup=main_menu(language),
    )


@router.message(CommandStart())
async def handle_start(message: Message, users: UserService, telegram_sender: TelegramSender) -> None:
    settings = await users.get(message.from_user.id)
    await _send_menu(message, settings.language, telegram_sender)


@router.message(Command("help"))
async def handle_help(message: Message, users: UserService, telegram_sender: TelegramSender) -> None:
    settings = await users.get(message.from_user.id)
    await telegram_sender.safe_tg_call(
        "ui",
        f"help:answer:{message.chat.id}:{message.message_id}",
        message.answer,
        get_text(settings.language, "help"),
        reply_markup=main_menu(settings.language),
    )


def _format_preview(events, tz: str, language: str) -> str:
    if not events:
        return get_text(language, "no_events")
    lines = [get_text(language, "event_list_header")]
    for event in events[:5]:
        local_time = to_local(event.starts_at, tz)
        lines.append(
            f"• {local_time.strftime('%d.%m %H:%M')} — {event.title} / {event.room} / {event.ticket}"
        )
    if len(events) > 5:
        lines.append("…")
    return "\n".join(lines)


async def _restore_menu(callback: CallbackQuery, language: str, sender: TelegramSender) -> None:
    if not callback.message:
        return

    async def _edit() -> None:
        try:
            await sender.safe_tg_call(
                "ui",
                f"menu:refresh:{callback.message.chat.id}:{callback.message.message_id}",
                callback.message.edit_text,
                get_text(language, "start"),
                reply_markup=main_menu(language),
            )
        except TelegramBadRequest:
            await sender.safe_tg_call(
                "ui",
                f"menu:refresh_markup:{callback.message.chat.id}:{callback.message.message_id}",
                callback.message.edit_reply_markup,
                reply_markup=main_menu(language),
            )

    asyncio.create_task(_edit())


@router.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def handle_menu_callback(
    callback: CallbackQuery,
    users: UserService,
    chats: ChatService,
    events: EventsService,
    telegram_sender: TelegramSender,
) -> None:
    if not callback.message:
        return
    settings = await users.get(callback.from_user.id)
    command = callback.data.split(":", maxsplit=1)[1]
    language = settings.language

    if command == "help":
        await telegram_sender.safe_tg_call(
            "ui",
            f"menu:help:{callback.from_user.id}",
            callback.message.answer,
            get_text(language, "help"),
        )
    elif command == "settings":
        await telegram_sender.safe_tg_call(
            "ui",
            f"menu:settings:{callback.from_user.id}",
            callback.message.answer,
            "Используйте /settings для изменения параметров." if language == "ru" else "Use /settings to adjust preferences.",
        )
    elif command == "chat":
        if callback.message.chat.type == ChatType.PRIVATE:
            text = (
                "Добавьте меня в групповой чат и отправьте /admin для регистрации." if language == "ru"
                else "Add me to a group chat and use /admin to register it."
            )
            await telegram_sender.safe_tg_call(
                "ui",
                f"menu:chat:private:{callback.from_user.id}",
                callback.message.answer,
                text,
            )
        else:
            chat_title = callback.message.chat.full_name or callback.message.chat.title or str(callback.message.chat.id)
            chat_settings = await chats.get_settings(callback.message.chat.id, title=chat_title)
            upcoming = await events.list_events(chat_id=callback.message.chat.id)
            text = _format_preview(upcoming, chat_settings.timezone, language)
            await telegram_sender.safe_tg_call(
                "ui",
                f"menu:chat:list:{callback.message.chat.id}",
                callback.message.answer,
                text,
            )
    elif command == "my":
        upcoming = await events.list_events(creator_id=callback.from_user.id)
        text = _format_preview(upcoming, settings.timezone, language)
        await telegram_sender.safe_tg_call(
            "ui",
            f"menu:my:{callback.from_user.id}",
            callback.message.answer,
            text,
        )
    else:
        await telegram_sender.safe_tg_call(
            "ui",
            f"menu:start:{callback.from_user.id}",
            callback.message.answer,
            get_text(language, "start"),
        )

    await _restore_menu(callback, language, telegram_sender)
