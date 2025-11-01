"""Handlers for administrator only commands."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from aiogram import Dispatcher, Router, types
from aiogram.filters import Command

from bot.models.storage import ChatSettings, Meeting, MeetingStorage
from bot.services.reminder import ReminderService
from bot.utils.meeting_parser import MeetingCommand, parse_meeting_command


def create_router(
    storage: MeetingStorage,
    reminder: ReminderService,
    admin_ids: tuple[int, ...],
    admin_usernames: tuple[str, ...],
    default_lead_times: tuple[int, ...],
) -> Router:
    router = Router(name="admin-handlers")

    def is_admin(message: types.Message) -> bool:
        if not message.from_user:
            return False
        user_id = message.from_user.id
        username = (message.from_user.username or "").lower()
        if user_id in admin_ids or username in admin_usernames:
            return True
        if message.chat:
            return storage.has_chat_role(message.chat.id, user_id, ("admin",))
        return False

    async def ensure_admin(message: types.Message) -> bool:
        if not is_admin(message):
            await message.answer("Эта команда доступна только администраторам.")
            return False
        if (
            message.chat
            and message.chat.type != "private"
            and not storage.is_chat_registered(message.chat.id)
        ):
            await message.answer(
                "Чат не зарегистрирован. Используйте /register_chat, чтобы настроить напоминания."
            )
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

    def format_lead_times(settings: ChatSettings) -> str:
        values = settings.lead_times
        if not values:
            return "не настроены"
        return ", ".join(ReminderService._format_lead_time(value) for value in values)

    def parse_duration(token: str) -> Optional[int]:
        token = token.strip().lower()
        if not token:
            return None
        multiplier = 60
        if token.endswith("h"):
            multiplier = 3600
            token = token[:-1]
        elif token.endswith("m"):
            multiplier = 60
            token = token[:-1]
        elif token.endswith("s"):
            multiplier = 1
            token = token[:-1]
        try:
            value = int(token)
        except ValueError:
            return None
        if value < 0:
            return None
        return value * multiplier

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

    async def execute_command(
        message: types.Message, command: MeetingCommand, now: datetime
    ) -> None:
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
            chat_id = message.chat.id if message.chat else command.chat_id
            if command.chat_id and message.chat and command.chat_id != message.chat.id:
                await message.answer("Укажите корректный чат для создания встречи.")
                return
            if chat_id is None:
                await message.answer("Создавать встречи можно только в зарегистрированных чатах.")
                return
            if not storage.is_chat_registered(chat_id):
                await message.answer("Укажите зарегистрированный чат для создания встречи.")
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
                chat_id=chat_id,
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
            target_chat = command.chat_id or (message.chat.id if message.chat else None)
            if target_chat and meeting.chat_id and meeting.chat_id != target_chat:
                await message.answer("Эта встреча принадлежит другому чату.")
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
            target_chat = command.chat_id or (message.chat.id if message.chat else None)
            if target_chat and meeting.chat_id and meeting.chat_id != target_chat:
                await message.answer("Эта встреча принадлежит другому чату.")
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
            target_chat = command.chat_id or (message.chat.id if message.chat else None)
            if target_chat and meeting.chat_id and meeting.chat_id != target_chat:
                await message.answer("Эта встреча принадлежит другому чату.")
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

    @router.message(Command("register_chat"))
    async def handle_register_chat(message: types.Message) -> None:
        if not message.chat:
            await message.answer("Команда доступна только в чате.")
            return
        if not message.from_user:
            await message.answer("Не удалось определить пользователя.")
            return
        if message.from_user.id not in admin_ids and (
            (message.from_user.username or "").lower() not in admin_usernames
        ):
            await message.answer("Команда доступна только глобальным администраторам.")
            return
        chat = storage.register_chat(
            message.chat.id,
            message.chat.title or message.chat.full_name,
            lead_times=default_lead_times or reminder.default_lead_times,
            admin_ids=[message.from_user.id],
        )
        await reminder.send_due_reminders()
        await message.answer(
            "Чат зарегистрирован. Текущие интервалы напоминаний: {intervals}.".format(
                intervals=format_lead_times(chat)
            )
        )

    @router.message(Command("set_lead_times"))
    async def handle_set_lead_times(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        if not message.chat:
            await message.answer("Команда доступна только в чате.")
            return
        args = message.text.split()[1:] if message.text else []
        if not args:
            await message.answer(
                "Использование: /set_lead_times <минуты...>\nПример: /set_lead_times 30 10 0"
            )
            return
        lead_times: list[int] = []
        for token in args:
            duration = parse_duration(token)
            if duration is None:
                await message.answer(f"Неверное значение: {token}")
                return
            lead_times.append(duration)
        updated = storage.set_chat_lead_times(message.chat.id, lead_times)
        if not updated:
            await message.answer("Не удалось обновить интервалы напоминаний.")
            return
        await reminder.send_due_reminders()
        await message.answer(
            "Интервалы напоминаний обновлены: {intervals}.".format(
                intervals=format_lead_times(updated)
            )
        )

    @router.message(Command("chat_settings"))
    async def handle_chat_settings(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        if not message.chat:
            await message.answer("Команда доступна только в чате.")
            return
        chat = storage.get_chat(message.chat.id)
        if not chat:
            await message.answer("Чат не зарегистрирован.")
            return
        admins = ", ".join(str(admin) for admin in chat.admin_ids) or "не назначены"
        await message.answer(
            "Настройки чата:\n"
            f"ID: {chat.id}\n"
            f"Интервалы: {format_lead_times(chat)}\n"
            f"Администраторы: {admins}"
        )

    @router.message(Command("add_chat_admin"))
    async def handle_add_chat_admin(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        if not message.chat:
            await message.answer("Команда доступна только в чате.")
            return
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.answer("Ответьте на сообщение пользователя, чтобы выдать права администратора.")
            return
        added = storage.add_chat_admin(message.chat.id, message.reply_to_message.from_user.id)
        if not added:
            await message.answer("Чат не зарегистрирован.")
            return
        await message.answer(
            "Пользователь {user} добавлен в администраторы.".format(
                user=message.reply_to_message.from_user.full_name
            )
        )

    @router.message(Command("remove_chat_admin"))
    async def handle_remove_chat_admin(message: types.Message) -> None:
        if not await ensure_admin(message):
            return
        if not message.chat:
            await message.answer("Команда доступна только в чате.")
            return
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.answer("Ответьте на сообщение пользователя, чтобы убрать его из администраторов.")
            return
        removed = storage.remove_chat_admin(message.chat.id, message.reply_to_message.from_user.id)
        if not removed:
            await message.answer("Чат не зарегистрирован.")
            return
        await message.answer(
            "Пользователь {user} удалён из списка администраторов.".format(
                user=message.reply_to_message.from_user.full_name
            )
        )

    return router


def register(
    dispatcher: Dispatcher,
    storage: MeetingStorage,
    reminder: ReminderService,
    admin_ids: tuple[int, ...],
    admin_usernames: tuple[str, ...],
    default_lead_times: tuple[int, ...],
) -> None:
    dispatcher.include_router(
        create_router(storage, reminder, admin_ids, admin_usernames, default_lead_times)
    )
