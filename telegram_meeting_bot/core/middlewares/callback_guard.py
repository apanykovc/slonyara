from __future__ import annotations

import logging

import asyncio

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
from typing import Any, Awaitable, Callable, Dict

from ...utils import locks
from ...keyboards.inline import freeze_keyboard
from ...services.telegram import TelegramSender


audit_logger = logging.getLogger("telegram_meeting_bot.audit")


class CallbackGuardMiddleware(BaseMiddleware):
    def __init__(self, guard: locks.ClickGuard, sender: TelegramSender) -> None:
        self._guard = guard
        self._sender = sender

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not event.message:
            return await handler(event, data)
        chat_id = event.message.chat.id
        message_id = event.message.message_id
        accepted = await self._guard.acquire(chat_id, message_id)
        if not accepted:
            audit_logger.info(
                '{"event":"CLICK_DEDUP","chat_id":%s,"message_id":%s}', chat_id, message_id
            )
            await self._sender.safe_tg_call(
                "ui",
                f"cb:dedup:{chat_id}:{message_id}",
                event.answer,
                "Уже обрабатываю…",
                show_alert=False,
            )
            return
        await self._sender.safe_tg_call(
            "ui",
            f"cb:ack:{chat_id}:{message_id}:{event.id}",
            event.answer,
            "Принято…",
            show_alert=False,
        )
        if event.message.reply_markup:
            version = event.id[-8:] if event.id else None
            frozen = freeze_keyboard(event.message.reply_markup, version=version)
            await self._sender.safe_tg_call(
                "ui",
                f"cb:freeze:{chat_id}:{message_id}:{event.id}",
                event.message.edit_reply_markup,
                reply_markup=frozen,
            )
        try:
            return await handler(event, data)
        finally:
            asyncio.create_task(self._guard.release_later(chat_id, message_id))
