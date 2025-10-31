from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class ClickState:
    expires_at: float


class ClickGuard:
    def __init__(self, window: float = 20.0) -> None:
        self._window = window
        self._locks: Dict[Tuple[int, int], ClickState] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, chat_id: int, message_id: int) -> bool:
        async with self._lock:
            key = (chat_id, message_id)
            now = time.monotonic()
            state = self._locks.get(key)
            if state and state.expires_at > now:
                return False
            self._locks[key] = ClickState(expires_at=now + self._window)
            return True

    async def release(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            self._locks.pop((chat_id, message_id), None)

    async def release_later(self, chat_id: int, message_id: int) -> None:
        await asyncio.sleep(self._window)
        await self.release(chat_id, message_id)

    async def cleanup(self) -> None:
        async with self._lock:
            now = time.monotonic()
            for key, state in list(self._locks.items()):
                if state.expires_at <= now:
                    self._locks.pop(key, None)
