"""Handlers for user facing bot commands."""
from __future__ import annotations

from datetime import datetime

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command, CommandStart

from bot.models.storage import MeetingStorage
from bot.utils.meeting_parser import parse_meeting_command


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
            "/schedule — список встреч этого чата\n"
            "/help — показать эту справку"
        )

    @router.message(Command("meetings"))
    async def handle_meetings(message: types.Message) -> None:
        if not message.from_user:
            await message.answer("Не удалось определить пользователя.")
            return

        chat_id = message.chat.id if message.chat else None
        meetings = storage.list_meetings_for_user(message.from_user.id, chat_id=chat_id)
        if not meetings:
            await message.answer("У вас пока нет запланированных встреч.")
            return

        lines = ["Ваши ближайшие встречи:"]
        for meeting in meetings:
            when = meeting.scheduled_at.strftime("%d.%m.%Y %H:%M")
            parts: list[str] = []
            if meeting.meeting_type:
                parts.append(meeting.meeting_type)
            elif meeting.title:
                parts.append(meeting.title)
            if meeting.room:
                parts.append(f"Переговорная {meeting.room}")
            if meeting.request_number:
                parts.append(f"Заявка {meeting.request_number}")
            title = " — ".join(parts) if parts else meeting.title or "Встреча"
            lines.append(f"• {title} ({when})")
        await message.answer("\n".join(lines))

    @router.message(Command("schedule"))
    async def handle_schedule(message: types.Message) -> None:
        if not message.chat:
            await message.answer("Команда доступна только в групповых чатах.")
            return
        meetings = storage.list_meetings_for_chat(message.chat.id)
        if not meetings:
            await message.answer("В этом чате пока нет запланированных встреч.")
            return
        lines = ["Расписание встреч чата:"]
        for meeting in meetings:
            when = meeting.scheduled_at.strftime("%d.%m.%Y %H:%M")
            parts: list[str] = []
            if meeting.meeting_type:
                parts.append(meeting.meeting_type)
            elif meeting.title:
                parts.append(meeting.title)
            if meeting.room:
                parts.append(f"Переговорная {meeting.room}")
            if meeting.request_number:
                parts.append(f"Заявка {meeting.request_number}")
            title = " — ".join(parts) if parts else meeting.title or "Встреча"
            lines.append(f"• {when} — {title}")
        await message.answer("\n".join(lines))

    @router.message()
    async def handle_shortcut_creation(message: types.Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        if not message.from_user or not message.chat:
            return
        chat_id = message.chat.id
        if not storage.is_chat_registered(chat_id):
            return
        now = datetime.now(tz=storage.timezone)
        command = parse_meeting_command(message.text, now)
        if not command:
            return
        if command.action != "create":
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        if not command.scheduled_at:
            await message.answer("Не удалось определить дату и время встречи.")
            return
        if command.request_number:
            existing = storage.find_meeting_by_request_number(command.request_number)
            if existing:
                await message.answer("Встреча с таким номером заявки уже существует.")
                return
        meeting_type = command.meeting_type or "Встреча"
        title = meeting_type
        if command.room:
            title = f"{meeting_type} ({command.room})"
        meeting = storage.create_meeting(
            title=title,
            scheduled_at=command.scheduled_at,
            organizer_id=message.from_user.id,
            meeting_type=command.meeting_type,
            room=command.room,
            request_number=command.request_number,
            participants=[message.from_user.id],
            chat_id=chat_id,
        )
        await message.answer(
            "Встреча создана!\n"
            f"Когда: {meeting.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Номер заявки: {meeting.request_number or '—'}"
        )

    return router


def register(dispatcher: Dispatcher, storage: MeetingStorage) -> None:
    """Register router within provided dispatcher."""

    dispatcher.include_router(create_router(storage))
