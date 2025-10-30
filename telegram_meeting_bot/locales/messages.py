from __future__ import annotations

from dataclasses import dataclass
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Texts:
    start: str
    help: str
    settings_saved: str
    reminder_scheduled: str
    reminder_cancelled: str
    event_list_header: str
    no_events: str
    reminder_message: str
    error_parse: str
    permission_denied: str
    conflict_detected: str
    conflict_options: str
    digest_header: str
    export_ready: str
    import_done: str
    seed_done: str
    status_template: str


MESSAGES: Dict[str, Texts] = {
    "ru": Texts(
        start="Привет! Я помогу с напоминаниями о встречах.",
        help=(
            "Отправьте сообщение в формате `30.10 МТС 10:00 7А 102455` "
            "или `завтра 10:00 МТС 7А 102455`. Используйте кнопки для управления."
        ),
        settings_saved="Настройки сохранены.",
        reminder_scheduled="Напоминание создано.",
        reminder_cancelled="Встреча отменена.",
        event_list_header="Ближайшие встречи:",
        no_events="Нет предстоящих встреч.",
        reminder_message="Напоминание: {title} в {room} ({ticket}) в {time}",
        error_parse="Не удалось распознать событие. Используйте формат 30.10 ТИП 10:00 7А 102455.",
        permission_denied="Недостаточно прав для выполнения действия.",
        conflict_detected="Обнаружен конфликт встреч:",
        conflict_options="Выберите действие:",
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
    ),
    "en": Texts(
        start="Hi! I will remind you about meetings.",
        help=(
            "Send a message like `30.10 TAG 10:00 7A 102455` "
            "or `tomorrow 10:00 TAG 7A 102455`. Use inline buttons to manage."
        ),
        settings_saved="Settings saved.",
        reminder_scheduled="Reminder scheduled.",
        reminder_cancelled="Meeting cancelled.",
        event_list_header="Upcoming meetings:",
        no_events="No upcoming meetings.",
        reminder_message="Reminder: {title} in {room} ({ticket}) at {time}",
        error_parse="Failed to parse message. Use 30.10 TYPE 10:00 7A 102455 format.",
        permission_denied="You do not have permission.",
        conflict_detected="A conflict was detected:",
        conflict_options="Choose what to do:",
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
    ),
}


def get_text(language: str, key: str, **kwargs: str) -> str:
    texts = MESSAGES.get(language, MESSAGES["ru"])
    value = getattr(texts, key)
    if kwargs:
        return value.format(**kwargs)
    return value
