from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

from ..config import BotConfig
from ..models.user import PreferredDestination, UserSettings
from ..storage.factory import create_storage

logger = logging.getLogger("telegram_meeting_bot.services.users")


class UserService:
    def __init__(self, config: BotConfig) -> None:
        self._storage = create_storage(config, "users", UserSettings, "user_id")
        self._cache: Dict[int, UserSettings] = {}
        self._default_tz = config.timezone
        self._default_lead = config.default_lead_time_minutes

    async def get(self, user_id: int) -> UserSettings:
        if user_id in self._cache:
            return self._cache[user_id]
        users = await self._storage.load_all()
        for user in users:
            self._cache[user.user_id] = user
        if user_id not in self._cache:
            settings = UserSettings(
                user_id=user_id,
                timezone=self._default_tz,
                lead_time_minutes=self._default_lead,
            )
            self._cache[user_id] = settings
            await self._storage.save_all(self._cache.values())
        return self._cache[user_id]

    async def update(self, settings: UserSettings) -> None:
        self._cache[settings.user_id] = settings
        await self._storage.save_all(self._cache.values())

    async def all(self) -> list[UserSettings]:
        users = await self._storage.load_all()
        for user in users:
            self._cache[user.user_id] = user
        return list(self._cache.values())

    async def mark_digest(self, user_id: int, moment: datetime) -> None:
        settings = await self.get(user_id)
        settings.last_digest_sent = moment
        await self.update(settings)

    async def set_preferred_destination(
        self,
        user_id: int,
        *,
        kind: str,
        chat_id: int | None = None,
        thread_id: int | None = None,
    ) -> None:
        settings = await self.get(user_id)
        settings.preferred_destination = PreferredDestination(
            kind=kind,
            chat_id=chat_id,
            thread_id=thread_id,
        )
        await self.update(settings)
