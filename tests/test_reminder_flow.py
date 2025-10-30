import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram_meeting_bot.config import BotConfig, NetworkConfig
from telegram_meeting_bot.services.chats import ChatService
from telegram_meeting_bot.services.events import EventsService
from telegram_meeting_bot.services.reminders import ReminderService
from telegram_meeting_bot.services.telegram import TelegramSender
from telegram_meeting_bot.services.users import UserService
from telegram_meeting_bot.utils.metrics import MetricsCollector


class FakeBot(SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.sent_messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return kwargs


def test_reminder_lifecycle(tmp_path):
    async def scenario():
        data_dir = tmp_path / "data"
        logs_dir = tmp_path / "logs"
        data_dir.mkdir()
        logs_dir.mkdir()
        config = BotConfig(
            token="test",
            data_dir=data_dir,
            logs_dir=logs_dir,
            default_lead_time_minutes=30,
            scheduler_tick_seconds=30,
            timezone="UTC",
            storage_backend="json",
            sqlite_path=None,
        )
        metrics = MetricsCollector()
        fake_bot = FakeBot()
        sender = TelegramSender(bot=fake_bot, network=NetworkConfig(), metrics=metrics)

        async def pump_sender(stop_event: asyncio.Event):
            while not stop_event.is_set():
                await sender.worker_tick()
                await asyncio.sleep(0.01)

        stop_event = asyncio.Event()
        pump_task = asyncio.create_task(pump_sender(stop_event))

        try:
            chats = ChatService(config)
            users = UserService(config)
            events = EventsService(config)
            reminders = ReminderService(
                events=events,
                chats=chats,
                users=users,
                metrics=metrics,
                bot_config=config,
                sender=sender,
            )

            start_time = datetime.now(timezone.utc) + timedelta(minutes=20)
            event = await events.create_event(
                creator_id=1,
                chat_id=None,
                thread_id=None,
                target_chat_id=1,
                title="МТС",
                room="7А",
                ticket="102455",
                starts_at=start_time,
                lead_time_minutes=30,
            )

            await reminders.dispatch_due_events()
            await asyncio.sleep(0.05)

            assert fake_bot.sent_messages

            await events.snooze(event.id, minutes=15)
            new_time = start_time + timedelta(hours=1)
            await events.reschedule_event(event.id, new_time)
            await events.cancel_event(event.id)
        finally:
            stop_event.set()
            await asyncio.sleep(0.01)
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task

    asyncio.run(scenario())
