from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import BotConfig
from ..locales import get_text
from ..keyboards.inline import event_actions
from ..models.event import Event
from ..utils.datetime import to_local, now_utc
from ..utils.texts import format_event_line
from ..utils.metrics import MetricsCollector
from .chats import ChatService
from .events import EventsService
from .users import UserService
from .telegram import TelegramSender

logger = logging.getLogger("telegram_meeting_bot.services.reminders")
audit_logger = logging.getLogger("telegram_meeting_bot.audit")


def _is_quiet(hours: tuple[int | None, int | None], local_time: datetime) -> bool:
    start, end = hours
    if start is None or end is None:
        return False
    hour = local_time.hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


class ReminderService:
    def __init__(
        self,
        *,
        events: EventsService,
        chats: ChatService,
        users: UserService,
        metrics: MetricsCollector,
        bot_config: BotConfig,
        sender: TelegramSender,
    ) -> None:
        self._events = events
        self._chats = chats
        self._users = users
        self._metrics = metrics
        self._bot_config = bot_config
        self._sender = sender

    async def dispatch_due_events(self) -> None:
        due_events = await self._events.due_events()
        if not due_events:
            return
        await self._metrics.set(queue_size=len(due_events))
        for event in due_events:
            await self._handle_event(event)
            await asyncio.sleep(0.3)
        await self._metrics.set(queue_size=0)

    async def _handle_event(self, event: Event) -> None:
        target_chat_id = event.target_chat_id or event.chat_id or event.creator_id
        if target_chat_id is None:
            return
        disable_notification = False
        language = "ru"
        thread_id = event.thread_id
        tz = self._bot_config.timezone

        remind_time = event.starts_at
        if event.chat_id:
            chat_settings = await self._chats.get_settings(event.chat_id)
            tz = chat_settings.timezone
            language = chat_settings.language
            local_time = to_local(remind_time - timedelta(minutes=event.lead_time_minutes), chat_settings.timezone)
            disable_notification = _is_quiet(
                (chat_settings.quiet_hours_start, chat_settings.quiet_hours_end), local_time
            )
        else:
            user_settings = await self._users.get(event.creator_id)
            tz = user_settings.timezone
            language = user_settings.language
            local_time = to_local(remind_time - timedelta(minutes=event.lead_time_minutes), user_settings.timezone)
            disable_notification = _is_quiet(
                (user_settings.quiet_hours_start, user_settings.quiet_hours_end), local_time
            )

        local_time = to_local(event.starts_at, tz)
        text = get_text(
            language,
            "reminder_message",
            title=event.title,
            room=event.room,
            ticket=event.ticket,
            time=local_time.strftime("%d.%m %H:%M"),
        )

        op_id = f"reminder:{event.id}:{event.starts_at.isoformat()}"
        is_admin = True
        if event.chat_id:
            is_admin = await self._chats.is_admin(event.chat_id, event.creator_id)

        success = await self._sender.safe_tg_call(
            "heavy",
            op_id,
            self._sender.bot.send_message,
            chat_id=target_chat_id,
            text=text,
            disable_notification=disable_notification,
            message_thread_id=thread_id,
            reply_markup=event_actions(event.id, is_admin),
        )
        if success:
            await self._events.mark_fired(event.id)
            audit_logger.info(
                '{"event":"REM_FIRED","event_id":"%s","chat_id":%s}', event.id, target_chat_id
            )

    async def dispatch_daily_digest(self) -> None:
        now = now_utc()
        await self._dispatch_chat_digest(now)
        await self._dispatch_user_digest(now)

    async def _dispatch_chat_digest(self, now: datetime) -> None:
        chats = await self._chats.all_settings()
        for chat in chats:
            if not chat.registered:
                continue
            local_now = to_local(now, chat.timezone)
            if local_now.hour != 9:
                continue
            if chat.last_digest_sent:
                last = to_local(chat.last_digest_sent, chat.timezone).date()
                if last == local_now.date():
                    continue
            start_local = datetime(
                local_now.year,
                local_now.month,
                local_now.day,
                tzinfo=ZoneInfo(chat.timezone),
            )
            start = start_local.astimezone(timezone.utc)
            end = (start_local + timedelta(days=1)).astimezone(timezone.utc)
            events = await self._events.list_events(
                chat_id=chat.chat_id,
                date_from=start,
                date_to=end,
                future_only=False,
            )
            if not events:
                continue
            lines = [get_text(chat.language, "digest_header", date=local_now.strftime("%d.%m.%Y"))]
            for event in events:
                lines.append(
                    f"• {format_event_line(event, chat.timezone, chat.language, include_date=False)}"
                )
            text = "\n".join(lines)
            await self._sender.safe_tg_call(
                "heavy",
                f"digest:chat:{chat.chat_id}:{local_now.date()}",
                self._sender.bot.send_message,
                chat_id=chat.chat_id,
                text=text,
                message_thread_id=chat.message_thread_id,
            )
            await self._chats.mark_digest(chat.chat_id, now)

    async def _dispatch_user_digest(self, now: datetime) -> None:
        users = await self._users.all()
        for user in users:
            if not user.direct_notifications:
                continue
            local_now = to_local(now, user.timezone)
            if local_now.hour != 9:
                continue
            if user.last_digest_sent:
                last = to_local(user.last_digest_sent, user.timezone).date()
                if last == local_now.date():
                    continue
            start_local = datetime(
                local_now.year,
                local_now.month,
                local_now.day,
                tzinfo=ZoneInfo(user.timezone),
            )
            start = start_local.astimezone(timezone.utc)
            end = (start_local + timedelta(days=1)).astimezone(timezone.utc)
            events = await self._events.list_events(
                creator_id=user.user_id,
                date_from=start,
                date_to=end,
                future_only=False,
            )
            if not events:
                continue
            lines = [get_text(user.language, "digest_header", date=local_now.strftime("%d.%m.%Y"))]
            for event in events:
                lines.append(
                    f"• {format_event_line(event, user.timezone, user.language, include_date=False)}"
                )
            text = "\n".join(lines)
            await self._sender.safe_tg_call(
                "heavy",
                f"digest:user:{user.user_id}:{local_now.date()}",
                self._sender.bot.send_message,
                chat_id=user.user_id,
                text=text,
            )
            await self._users.mark_digest(user.user_id, now)

