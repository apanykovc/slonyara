from __future__ import annotations

try:  # pragma: no cover - optional aiogram dependency in test environment
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
except ModuleNotFoundError:  # pragma: no cover
    from dataclasses import dataclass

    @dataclass
    class InlineKeyboardButton:  # type: ignore[misc]
        text: str
        callback_data: str | None = None

    class InlineKeyboardMarkup:  # type: ignore[misc]
        def __init__(self, inline_keyboard: list[list[InlineKeyboardButton]] | None = None) -> None:
            self.inline_keyboard = inline_keyboard or []


def noop_button(text: str, version: str | None = None) -> InlineKeyboardButton:
    suffix = f":{version}" if version else ""
    return InlineKeyboardButton(text=text, callback_data=f"noop{suffix}")


def main_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мои встречи" if language == "ru" else "📅 My meetings", callback_data="menu:my")],
            [
                InlineKeyboardButton(
                    text="👥 Встречи чата" if language == "ru" else "👥 Chat meetings",
                    callback_data="menu:chat",
                )
            ],
            [InlineKeyboardButton(text="⚙️ Настройки" if language == "ru" else "⚙️ Settings", callback_data="menu:settings")],
            [InlineKeyboardButton(text="❓ Помощь" if language == "ru" else "❓ Help", callback_data="menu:help")],
        ]
    )


def events_pagination(page: int, total: int, prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    if total > 1:
        buttons.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:prev:{page}")
        )
        buttons.append(noop_button(f"{page}/{total}"))
        buttons.append(
            InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:next:{page}")
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])


def event_actions(event_id: str, is_admin: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔁 +15 мин", callback_data=f"event:snooze:{event_id}")]
    ]
    if is_admin:
        buttons.extend(
            [
                [InlineKeyboardButton(text="✏️ Перенести", callback_data=f"event:move:{event_id}")],
                [InlineKeyboardButton(text="❌ Отменить", callback_data=f"event:cancel:{event_id}")],
                [InlineKeyboardButton(text="📆 Повтор ежедневно", callback_data=f"event:repeat:daily:{event_id}")],
                [InlineKeyboardButton(text="📆 Повтор еженедельно", callback_data=f"event:repeat:weekly:{event_id}")],
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_menu(language: str, include_registration: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⏰ Lead time", callback_data="settings:lead")],
        [InlineKeyboardButton(text="🌍 Часовой пояс" if language == "ru" else "🌍 Timezone", callback_data="settings:tz")],
        [InlineKeyboardButton(text="🔕 Тихие часы", callback_data="settings:quiet")],
        [InlineKeyboardButton(text="🌐 Language", callback_data="settings:lang")],
    ]
    if include_registration:
        rows.append([InlineKeyboardButton(text="💬 Регистрация чата", callback_data="settings:register")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def freeze_keyboard(markup: InlineKeyboardMarkup, version: str | None = None) -> InlineKeyboardMarkup:
    if not markup.inline_keyboard:
        return markup
    frozen = []
    suffix = f":{version}" if version else ""
    for row in markup.inline_keyboard:
        frozen.append(
            [InlineKeyboardButton(text=f"⏳ {button.text}", callback_data=f"noop{suffix}") for button in row]
        )
    return InlineKeyboardMarkup(inline_keyboard=frozen)


def conflict_resolution(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏱️ Сдвинуть +15 минут", callback_data=f"conflict:snooze:{draft_id}")],
            [InlineKeyboardButton(text="🏢 Другая переговорная", callback_data=f"conflict:room:{draft_id}")],
            [InlineKeyboardButton(text="🚫 Отменить", callback_data=f"conflict:cancel:{draft_id}")],
        ]
    )


def conflict_room_menu(draft_id: str, rooms: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=room, callback_data=f"conflict:setroom:{draft_id}:{room}")] for room in rooms]
    rows.append([InlineKeyboardButton(text="✏️ Ввести вручную", callback_data=f"conflict:manual:{draft_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"conflict:back:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu(include_roles: bool, include_registration: bool, language: str) -> InlineKeyboardMarkup:
    rows = []
    if include_registration:
        rows.append([InlineKeyboardButton(text="💬 Регистрация чата", callback_data="admin:register")])
    if include_roles:
        rows.append([InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin:grant")])
        rows.append([InlineKeyboardButton(text="➖ Снять админа", callback_data="admin:revoke")])
    rows.append([InlineKeyboardButton(text="📊 Статус", callback_data="admin:status")])
    rows.append([InlineKeyboardButton(text="📦 Миграция", callback_data="admin:migrate")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
