"""Handlers for administrator only commands."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command

from bot.models.storage import Meeting, MeetingStorage
from bot.services.reminder import ReminderService
from bot.utils.meeting_parser import MeetingCommand, parse_meeting_command


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

    def current_time() -> datetime:
        tz = storage.timezone
        return datetime.now(tz=tz)

    def compose_title(meeting_type: Optional[str], room: Optional[str], fallback: str) -> str:
        base = meeting_type or fallback or "Встреча"
        if room:
            return f"{base} ({room})"
        return base

    def render_summary(meeting: Meeting) -> str:
        when = meeting.scheduled_at.strftime("%d.%m.%Y %H:%M")
        lines = [f"🕒 {when}"]
        if meeting.meeting_type:
            lines.append(f"Тип: {meeting.meeting_type}")
        else:
            lines.append(f"Название: {meeting.title}")
        if meeting.room:
            lines.append(f"Переговорная: {meeting.room}")
        if meeting.request_number:
            lines.append(f"Заявка: {meeting.request_number}")
        lines.append(
            "Участники: {participants}".format(
                participants=", ".join(str(pid) for pid in meeting.participants)
            )
        )
        return "\n".join(lines)

    def ensure_unique_request(number: str, *, exclude: Optional[str] = None) -> bool:
        existing = storage.find_meeting_by_request_number(number)
        return not existing or existing.id == exclude

    def apply_partial_datetime(
        original: datetime,
        command: MeetingCommand,
        now: datetime,
    ) -> tuple[datetime, bool]:
        updated = original
        changed = False
        if command.date_parts:
            day, month, year_hint = command.date_parts
            target_year = year_hint or original.year
            try:
                updated = updated.replace(year=target_year, month=month, day=day)
            except ValueError as exc:
                raise ValueError("Некорректная дата.") from exc
            if year_hint is None:
                reference = now
                if reference.tzinfo is None and updated.tzinfo is not None:
                    reference = reference.replace(tzinfo=updated.tzinfo)
                if updated < reference:
                    try:
                        updated = updated.replace(year=updated.year + 1)
                    except ValueError as exc:  # pragma: no cover - calendar edge case
                        raise ValueError("Некорректная дата.") from exc
            changed = True
        if command.time_parts:
            hour, minute = command.time_parts
            try:
                updated = updated.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError as exc:
                raise ValueError("Некорректное время.") from exc
            changed = True
        return updated, changed

    async def execute_command(message: types.Message, command: MeetingCommand, now: datetime) -> None:
        if command.action == "create":
            if message.from_user is None:
                await message.answer("Не удалось определить пользователя.")
                return
            if not command.scheduled_at:
                await message.answer("Не удалось определить дату и время встречи.")
                return
            if command.request_number and not ensure_unique_request(command.request_number):
                await message.answer("Встреча с таким номером заявки уже существует.")
                return
            meeting_type = command.meeting_type or "Встреча"
            title = compose_title(meeting_type, command.room, meeting_type)
            meeting = storage.create_meeting(
                title=title,
                scheduled_at=command.scheduled_at,
                organizer_id=message.from_user.id,
                meeting_type=command.meeting_type,
                room=command.room,
                request_number=command.request_number,
            )
            await message.answer("Встреча создана.\n" + render_summary(meeting))
            return

        if command.action == "cancel":
            if not command.request_number:
                await message.answer("Укажите номер заявки для отмены встречи.")
                return
            meeting = storage.find_meeting_by_request_number(command.request_number)
            if not meeting:
                await message.answer("Встреча с такой заявкой не найдена.")
                return
            storage.cancel_meeting(meeting.id)
            await message.answer("Встреча отменена.\n" + render_summary(meeting))
            return

        if command.action == "snooze":
            minutes = command.minutes_delta or 0
            if minutes <= 0:
                await message.answer("Укажите длительность сноуза в минутах.")
                return
            if command.request_number:
                meeting = storage.find_meeting_by_request_number(command.request_number)
            else:
                meetings = storage.list_meetings_for_user(message.from_user.id if message.from_user else 0)
                meeting = meetings[0] if meetings else None
            if not meeting:
                await message.answer("Не удалось найти встречу для переноса.")
                return
            new_time = meeting.scheduled_at + timedelta(minutes=minutes)
            updated = storage.update_meeting(meeting.id, scheduled_at=new_time)
            if not updated:
                await message.answer("Не удалось обновить встречу.")
                return
            await reminder.send_due_reminders()
            await message.answer("Встреча перенесена.\n" + render_summary(updated))
            return

        if command.action == "update":
            if not command.request_number:
                await message.answer("Укажите номер заявки для редактирования встречи.")
                return
            meeting = storage.find_meeting_by_request_number(command.request_number)
            if not meeting:
                await message.answer("Встреча с такой заявкой не найдена.")
                return

            schedule_target = meeting.scheduled_at
            schedule_changed = False
            if command.scheduled_at is not None:
                schedule_target = command.scheduled_at
                schedule_changed = True
            elif command.date_parts or command.time_parts:
                schedule_target, schedule_changed = apply_partial_datetime(meeting.scheduled_at, command, now)

            updates: dict[str, object] = {}
            if schedule_changed:
                updates["scheduled_at"] = schedule_target

            meeting_type = meeting.meeting_type
            room = meeting.room
            if command.meeting_type is not None:
                meeting_type = command.meeting_type
                updates["meeting_type"] = meeting_type
            if command.room is not None:
                room = command.room
                updates["room"] = room
            if command.new_request_number is not None:
                if not ensure_unique_request(command.new_request_number, exclude=meeting.id):
                    await message.answer("Встреча с таким номером заявки уже существует.")
                    return
                updates["request_number"] = command.new_request_number

            if updates:
                updates["title"] = compose_title(meeting_type, room, meeting.title)
                updated = storage.update_meeting(meeting.id, **updates)
                if not updated:
                    await message.answer("Не удалось обновить встречу.")
                    return
                if schedule_changed:
                    await reminder.send_due_reminders()
                await message.answer("Встреча обновлена.\n" + render_summary(updated))
            else:
                await message.answer("Изменений не обнаружено.")

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

        if message.from_user is None:
            await message.answer("Не удалось определить пользователя.")
            return

        meeting = storage.create_meeting(
            title=title,
            scheduled_at=scheduled_at,
            organizer_id=message.from_user.id,
            meeting_type=title,
        )
        await message.answer("Встреча создана!\n" + render_summary(meeting))

    @router.message(Command("cancel_meeting"))
    async def handle_cancel(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        args = message.text.split(maxsplit=1) if message.text else []
        if len(args) < 2:
            await message.answer("Использование: /cancel_meeting <id>")
            return
        meeting_id = args[1].strip()
        meeting = storage.get_meeting(meeting_id)
        if not meeting or not storage.cancel_meeting(meeting_id):
            await message.answer("Встреча с таким ID не найдена.")
            return
        await message.answer("Встреча отменена.\n" + render_summary(meeting))

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
        meeting = storage.get_meeting(meeting_id)
        if not meeting or not storage.reschedule_meeting(meeting_id, new_time):
            await message.answer("Встреча с таким ID не найдена.")
            return
        await message.answer("Встреча успешно перенесена.\n" + render_summary(meeting))
        await reminder.send_due_reminders()

    @router.message()
    async def handle_shortcuts(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        if not message.text or message.text.startswith("/"):
            return
        now = current_time()
        command = parse_meeting_command(message.text, now)
        if not command:
            return
        try:
            await execute_command(message, command, now)
        except ValueError as exc:
            await message.answer(str(exc))

    return router


def register(
    dispatcher: Dispatcher,
    storage: MeetingStorage,
    reminder: ReminderService,
    admin_ids: tuple[int, ...],
) -> None:
    dispatcher.include_router(create_router(storage, reminder, admin_ids))
