"""Handlers for user facing bot commands."""
from __future__ import annotations

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command, CommandStart

from bot.models.storage import MeetingStorage


def create_router(storage: MeetingStorage) -> Router:
    router = Router(name="user-handlers")

    @router.message(CommandStart())
    async def handle_start(message: types.Message) -> None:
        user_full_name = message.from_user.full_name if message.from_user else "друг"
        await message.answer(
            "👋 Привет, {name}!\n"
            "Используй /help, чтобы узнать доступные команды.".format(name=user_full_name)
        )

    @router.message(Command("help"))
    async def handle_help(message: types.Message) -> None:
        await message.answer(
            "Доступные команды:\n"
            "/meetings — показать ваши встречи\n"
            "/help — показать эту справку"
        )

    @router.message(Command("meetings"))
    async def handle_meetings(message: types.Message) -> None:
        if not message.from_user:
            await message.answer("Не удалось определить пользователя.")
            return

        meetings = storage.list_meetings_for_user(message.from_user.id)
        if not meetings:
            await message.answer("У вас пока нет запланированных встреч.")
            return

        lines = ["Ваши ближайшие встречи:"]
        for meeting in meetings:
            lines.append(
                "• {title} — {when}".format(
                    title=meeting.title,
                    when=meeting.scheduled_at.strftime("%Y-%m-%d %H:%M"),
                )
            )
        await message.answer("\n".join(lines))

    return router


def register(dispatcher: Dispatcher, storage: MeetingStorage) -> None:
    """Register router within provided dispatcher."""

    dispatcher.include_router(create_router(storage))
