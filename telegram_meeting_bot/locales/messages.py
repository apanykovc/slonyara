from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Texts:
    start: str
    help: str
    settings_saved: str
    reminder_scheduled: str
    reminder_scheduled_target: str
    reminder_cancelled: str
    event_list_header: str
    no_events: str
    reminder_message: str
    error_parse: str
    permission_denied: str
    conflict_detected: str
    conflict_options: str
    conflict_reason_room: str
    conflict_reason_creator: str
    digest_header: str
    export_ready: str
    import_done: str
    seed_done: str
    status_template: str
    ticket_label: str
    choose_destination: str
    destination_personal: str
    destination_chat: str
    destination_cancelled: str
    agenda_today: str
    agenda_tomorrow: str
    agenda_week: str


MESSAGES: Dict[str, Texts] = {
    "ru": Texts(
        start=(
            "Привет! Я помогу с напоминаниями о встречах.\n"
            "• Отправьте строку вида `30.10 МТС 10:00 7А 102455`.\n"
            "• Или воспользуйтесь командой /create для пошагового мастера.\n"
            "Нажмите кнопку ниже, чтобы посмотреть встречи или открыть настройки."
        ),
        help=(
            "Я умею: \n"
            "• Создавать встречи по одной строке или через /create.\n"
            "• Показывать списки встреч (/events).\n"
            "• Напоминать за выбранный lead-time.\n"
            "• Экспортировать в календарь (/export).\n"
            "Используйте кнопки меню, чтобы быстро перейти к нужному действию."
        ),
        settings_saved="Настройки сохранены.",
        reminder_scheduled="Напоминание создано.",
        reminder_scheduled_target="Готово! {event}\nНапомним в {destination}.",
        reminder_cancelled="Встреча отменена.",
        event_list_header="Ближайшие встречи:",
        no_events="Нет предстоящих встреч.",
        reminder_message="Напоминание: {title} в {room} ({ticket}) в {time}",
        error_parse="Не удалось распознать событие. Используйте формат 30.10 ТИП 10:00 7А 102455.",
        permission_denied="Недостаточно прав для выполнения действия.",
        conflict_detected="Обнаружен конфликт встреч:",
        conflict_options="Выберите действие:",
        conflict_reason_room="та же переговорная",
        conflict_reason_creator="пересечение по создателю",
        digest_header="Встречи на {date}",
        export_ready="Файл экспорта готов.",
        import_done="Импорт завершён.",
        seed_done="Созданы тестовые встречи.",
        status_template=(
            "Очередь: {queue}\n"
            "Отправлено: {sends}\n"
            "Ретраи: {retries5}/5м, {retries60}/60м\n"
            "Таймауты: {timeouts5}/5м, {timeouts60}/60м\n"
            "p50/p95 (5м): {p50_5:.3f}s / {p95_5:.3f}s\n"
            "p50/p95 (60м): {p50_60:.3f}s / {p95_60:.3f}s\n"
            "Активные задачи: {tasks}"
        ),
        ticket_label="№",
        choose_destination="Куда отправить напоминание?",
        destination_personal="📬 Личные уведомления",
        destination_chat="💬 {title}",
        destination_cancelled="Создание напоминания отменено.",
        agenda_today="Встречи сегодня:",
        agenda_tomorrow="Встречи на завтра:",
        agenda_week="Встречи на ближайшие 7 дней:",
    ),
    "en": Texts(
        start=(
            "Hi! I help teams remember their meetings.\n"
            "• Send a line like `30.10 TAG 10:00 7A 102455`.\n"
            "• Or use /create to open a guided wizard.\n"
            "Pick a menu button below to review meetings or adjust settings."
        ),
        help=(
            "I can: \n"
            "• Create meetings from a single line or /create wizard.\n"
            "• Show upcoming lists (/events).\n"
            "• Ping you ahead of time using your lead time.\n"
            "• Export to calendar via /export.\n"
            "Use the inline menu to jump to common actions."
        ),
        settings_saved="Settings saved.",
        reminder_scheduled="Reminder scheduled.",
        reminder_scheduled_target="All set! {event}\nWe will notify in {destination}.",
        reminder_cancelled="Meeting cancelled.",
        event_list_header="Upcoming meetings:",
        no_events="No upcoming meetings.",
        reminder_message="Reminder: {title} in {room} ({ticket}) at {time}",
        error_parse="Failed to parse message. Use 30.10 TYPE 10:00 7A 102455 format.",
        permission_denied="You do not have permission.",
        conflict_detected="A conflict was detected:",
        conflict_options="Choose what to do:",
        conflict_reason_room="same room",
        conflict_reason_creator="overlaps with your schedule",
        digest_header="Meetings for {date}",
        export_ready="Export file is ready.",
        import_done="Import completed.",
        seed_done="Seed meetings created.",
        status_template=(
            "Queue: {queue}\n"
            "Sent: {sends}\n"
            "Retries: {retries5}/5m, {retries60}/60m\n"
            "Timeouts: {timeouts5}/5m, {timeouts60}/60m\n"
            "p50/p95 (5m): {p50_5:.3f}s / {p95_5:.3f}s\n"
            "p50/p95 (60m): {p50_60:.3f}s / {p95_60:.3f}s\n"
            "Active tasks: {tasks}"
        ),
        ticket_label="Ticket",
        choose_destination="Where should we deliver the reminder?",
        destination_personal="📬 Personal reminders",
        destination_chat="💬 {title}",
        destination_cancelled="Reminder creation cancelled.",
        agenda_today="Today's meetings:",
        agenda_tomorrow="Tomorrow's meetings:",
        agenda_week="Next 7 days:",
    ),
}


def get_text(language: str, key: str, **kwargs: str) -> str:
    texts = MESSAGES.get(language, MESSAGES["ru"])
    value = getattr(texts, key)
    if kwargs:
        return value.format(**kwargs)
    return value
