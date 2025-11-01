"""Handlers for user facing bot commands."""
from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command, CommandStart

from bot.models.storage import MeetingStorage
from bot.services.reminder import ReminderService
from bot.utils.meeting_parser import parse_meeting_command


def create_router(storage: MeetingStorage, reminder: ReminderService) -> Router:
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
        if chat_id and not storage.has_chat_role(chat_id, message.from_user.id, ("admin", "user")):
            await message.answer("У вас нет доступа к встречам этого чата.")
            return
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
        if not storage.has_chat_role(message.chat.id, message.from_user.id if message.from_user else 0, ("admin", "user")):
            await message.answer("У вас нет доступа к расписанию этого чата.")
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

    def _resolve_target_chat(
        message: types.Message, command_chat_id: int | None
    ) -> tuple[int | None, str | None]:
        if message.chat and message.chat.type != "private":
            chat_id = message.chat.id
            if command_chat_id and command_chat_id != chat_id:
                return None, "Укажите корректный чат через префикс #<id>."
            if not storage.is_chat_registered(chat_id):
                return None, "Этот чат не зарегистрирован для напоминаний."
            return chat_id, None

        chat_id = command_chat_id
        if chat_id is not None:
            if not storage.is_chat_registered(chat_id):
                return None, "Укажите зарегистрированный чат для проведения встречи."
            return chat_id, None

        if not message.from_user:
            return None, "Не удалось определить пользователя."

        available = storage.list_user_chats(message.from_user.id, roles=("admin", "user"))
        if not available:
            return None, "У вас нет доступных чатов. Укажите чат через префикс #<id>."
        if len(available) == 1:
            return available[0].id, None
        options = ", ".join(
            f"#{chat.id} — {chat.title or chat.id}" for chat in available
        )
        return None, "Укажите чат через префикс #<id>. Доступные чаты: {options}"

    @router.message()
    async def handle_shortcut_creation(message: types.Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        if not message.from_user or not message.chat:
            return
        now = datetime.now(tz=storage.timezone)
        command = parse_meeting_command(message.text, now)
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
            await message.answer("У вас нет прав для действий в этом чате.")
            return

        if command.action == "create":
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
                organizer_id=user_id,
                meeting_type=command.meeting_type,
                room=command.room,
                request_number=command.request_number,
                participants=[user_id],
                chat_id=chat_id,
            )
            await message.answer(
                "Встреча создана!\n"
                f"Когда: {meeting.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"Номер заявки: {meeting.request_number or '—'}"
            )
            return

        if command.action == "snooze":
            minutes = command.minutes_delta or 0
            if minutes not in (5, 10, 15):
                await message.answer("Доступны только сноузы на 5, 10 или 15 минут.")
                return
            if command.request_number:
                meeting = storage.find_meeting_by_request_number(command.request_number)
                if not meeting or (meeting.chat_id and meeting.chat_id != chat_id):
                    await message.answer("Встреча с таким номером заявки не найдена в этом чате.")
                    return
            else:
                meetings = storage.list_meetings_for_user(user_id, chat_id=chat_id)
                meeting = meetings[0] if meetings else None
            if not meeting:
                await message.answer("Не удалось найти встречу для переноса.")
                return
            if meeting.chat_id and meeting.chat_id != chat_id:
                await message.answer("Эта встреча принадлежит другому чату.")
                return
            if user_id not in meeting.participants and meeting.organizer_id != user_id:
                await message.answer("Можно переносить только свои встречи.")
                return
            new_time = meeting.scheduled_at + timedelta(minutes=minutes)
            updated = storage.update_meeting(meeting.id, scheduled_at=new_time)
            if not updated:
                await message.answer("Не удалось обновить встречу.")
                return
            await reminder.send_due_reminders()
            await message.answer(
                "Встреча перенесена.\n"
                f"Новый старт: {updated.scheduled_at.strftime('%d.%m.%Y %H:%M')}"
            )
            return

        await message.answer("У вас нет прав для выполнения этой команды.")

    return router


def register(dispatcher: Dispatcher, storage: MeetingStorage, reminder: ReminderService) -> None:
    """Register router within provided dispatcher."""

    dispatcher.include_router(create_router(storage, reminder))
