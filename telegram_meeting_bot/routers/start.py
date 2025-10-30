from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..keyboards.inline import main_menu
from ..locales import get_text
from ..services.users import UserService
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


async def _safe_edit(message: Message, text: str, markup, sender: TelegramSender) -> None:
    try:
        await sender.safe_tg_call(
            "heavy",
            f"menu:edit:{message.chat.id}:{message.message_id}",
            message.edit_text,
            text,
            reply_markup=markup,
        )
    except TelegramBadRequest:
        pass


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


@router.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def handle_menu_callback(callback: CallbackQuery, users: UserService, telegram_sender: TelegramSender) -> None:
    if not callback.message:
        return
    settings = await users.get(callback.from_user.id)
    command = callback.data.split(":", maxsplit=1)[1]
    if command == "help":
        text = get_text(settings.language, "help")
    elif command == "settings":
        text = "⚙️"
    elif command == "chat":
        text = "👥"
    else:
        text = get_text(settings.language, "start")
    asyncio.create_task(
        _safe_edit(callback.message, text, main_menu(settings.language), telegram_sender)
    )
