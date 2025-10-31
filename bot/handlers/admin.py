"""Handlers for administrator only commands."""
from __future__ import annotations

from datetime import datetime

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command

from bot.models.storage import MeetingStorage
from bot.services.reminder import ReminderService


def create_router(
    storage: MeetingStorage,
    reminder: ReminderService,
    admin_ids: tuple[int, ...],
) -> Router:
    router = Router(name="admin-handlers")

    def is_admin(message: types.Message) -> bool:
        return bool(message.from_user and message.from_user.id in admin_ids)

    async def ensure_admin(message: types.Message) -> bool:
        if not is_admin(message):
            await message.answer("Эта команда доступна только администраторам.")
            return False
        return True

    @router.message(Command("create_meeting"))
    async def handle_create(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        args = message.text.split(maxsplit=2) if message.text else []
        if len(args) < 3:
            await message.answer(
                "Использование: /create_meeting <ISO-время> <название>\n"
                "Например: /create_meeting 2024-01-01T12:00 Совещание"
            )
            return
        _, when_raw, title = args
        try:
            scheduled_at = datetime.fromisoformat(when_raw)
        except ValueError:
            await message.answer("Не удалось распарсить дату. Используйте формат YYYY-MM-DDTHH:MM")
            return

        meeting = storage.create_meeting(
            title=title,
            scheduled_at=scheduled_at,
            organizer_id=message.from_user.id,
        )
        await message.answer(
            "Встреча создана!\nID: {id}\nВремя: {when}".format(
                id=meeting.id,
                when=meeting.scheduled_at.strftime("%Y-%m-%d %H:%M"),
            )
        )

    @router.message(Command("cancel_meeting"))
    async def handle_cancel(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        args = message.text.split(maxsplit=1) if message.text else []
        if len(args) < 2:
            await message.answer("Использование: /cancel_meeting <id>")
            return
        meeting_id = args[1].strip()
        if not storage.cancel_meeting(meeting_id):
            await message.answer("Встреча с таким ID не найдена.")
            return
        await message.answer("Встреча отменена.")

    @router.message(Command("reschedule_meeting"))
    async def handle_reschedule(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        args = message.text.split(maxsplit=2) if message.text else []
        if len(args) < 3:
            await message.answer(
                "Использование: /reschedule_meeting <id> <ISO-время>"
            )
            return
        _, meeting_id, when_raw = args
        try:
            new_time = datetime.fromisoformat(when_raw)
        except ValueError:
            await message.answer("Не удалось распарсить дату. Используйте формат YYYY-MM-DDTHH:MM")
            return
        if not storage.reschedule_meeting(meeting_id, new_time):
            await message.answer("Встреча с таким ID не найдена.")
            return
        await message.answer("Встреча успешно перенесена.")
        await reminder.send_due_reminders()

    return router


def register(
    dispatcher: Dispatcher,
    storage: MeetingStorage,
    reminder: ReminderService,
    admin_ids: tuple[int, ...],
) -> None:
    dispatcher.include_router(create_router(storage, reminder, admin_ids))
