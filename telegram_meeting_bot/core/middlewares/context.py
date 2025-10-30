from __future__ import annotations

from aiogram import BaseMiddleware
from typing import Any, Callable, Dict, Awaitable


class ContextMiddleware(BaseMiddleware):
    def __init__(self, **services: Any) -> None:
        self._services = services

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        data.update(self._services)
        return await handler(event, data)
