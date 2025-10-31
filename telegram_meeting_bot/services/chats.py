from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

from ..config import BotConfig
from ..models.chat import ChatRole, ChatSettings
from ..storage.factory import create_storage

logger = logging.getLogger("telegram_meeting_bot.services.chats")


class ChatService:
    def __init__(self, config: BotConfig) -> None:
        self._settings_storage = create_storage(config, "chats", ChatSettings, "chat_id")
        self._roles_storage = create_storage(
            config,
            "roles",
            ChatRole,
            "role",
            key_getter=lambda data: f"{data['chat_id']}:{data['user_id']}",
        )
        self._settings: Dict[int, ChatSettings] = {}
        self._roles: Dict[tuple[int, int], ChatRole] = {}
        self._default_tz = config.timezone
        self._default_lead = config.default_lead_time_minutes

    async def get_settings(self, chat_id: int, title: str | None = None) -> ChatSettings:
        if chat_id in self._settings:
            return self._settings[chat_id]
        settings = await self._settings_storage.load_all()
        for item in settings:
            self._settings[item.chat_id] = item
        if chat_id not in self._settings:
            chat_settings = ChatSettings(
                chat_id=chat_id,
                title=title or str(chat_id),
                timezone=self._default_tz,
                lead_time_minutes=self._default_lead,
            )
            self._settings[chat_id] = chat_settings
            await self._settings_storage.save_all(self._settings.values())
        return self._settings[chat_id]

    async def update_settings(self, settings: ChatSettings) -> None:
        self._settings[settings.chat_id] = settings
        await self._settings_storage.save_all(self._settings.values())

    async def register_chat(
        self,
        *,
        chat_id: int,
        title: str,
        timezone: str,
        lead_time: int,
        thread_id: int | None,
    ) -> ChatSettings:
        settings = await self.get_settings(chat_id, title=title)
        settings.registered = True
        settings.title = title
        settings.timezone = timezone
        settings.lead_time_minutes = lead_time
        settings.message_thread_id = thread_id
        await self.update_settings(settings)
        logger.info("chat_registered chat_id=%s thread_id=%s", chat_id, thread_id)
        return settings

    async def set_role(self, chat_id: int, user_id: int, role: str) -> None:
        roles = await self._roles_storage.load_all()
        self._roles = {(item.chat_id, item.user_id): item for item in roles}
        self._roles[(chat_id, user_id)] = ChatRole(chat_id=chat_id, user_id=user_id, role=role)
        await self._roles_storage.save_all(self._roles.values())

    async def has_role(self, chat_id: int, user_id: int, role: str) -> bool:
        if not self._roles:
            roles = await self._roles_storage.load_all()
            self._roles = {(item.chat_id, item.user_id): item for item in roles}
        stored = self._roles.get((chat_id, user_id))
        return stored is not None and stored.role == role

    async def list_admins(self, chat_id: int) -> list[int]:
        if not self._roles:
            roles = await self._roles_storage.load_all()
            self._roles = {(item.chat_id, item.user_id): item for item in roles}
        return [user for (chat, user), role in self._roles.items() if chat == chat_id and role.role == "admin"]

    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        admins = await self.list_admins(chat_id)
        return not admins or user_id in admins

    async def all_settings(self) -> list[ChatSettings]:
        if not self._settings:
            settings = await self._settings_storage.load_all()
            for item in settings:
                self._settings[item.chat_id] = item
        return list(self._settings.values())

    async def mark_digest(self, chat_id: int, moment: datetime) -> None:
        settings = await self.get_settings(chat_id)
        settings.last_digest_sent = moment
        await self.update_settings(settings)
