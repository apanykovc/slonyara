import asyncio
from datetime import datetime, timedelta, timezone

from telegram_meeting_bot.config import BotConfig
from telegram_meeting_bot.services.events import EventsService


async def _create_service(tmp_path):
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
    service = EventsService(config)
    return service


def test_due_events_respect_lead_time(tmp_path):
    async def scenario():
        events_service = await _create_service(tmp_path)
        event = await events_service.create_event(
            creator_id=1,
            chat_id=1,
            thread_id=None,
            target_chat_id=1,
            title="МТС",
            room="7А",
            ticket="102455",
            starts_at=datetime.now(timezone.utc) + timedelta(minutes=20),
            lead_time_minutes=30,
        )

        due = await events_service.due_events()
        assert event in due


    asyncio.run(scenario())


def test_find_conflicts(tmp_path):
    async def scenario():
        events_service = await _create_service(tmp_path)
        base = datetime(2024, 10, 1, 12, tzinfo=timezone.utc)
        await events_service.create_event(
            creator_id=1,
            chat_id=1,
            thread_id=None,
            target_chat_id=1,
            title="МТС",
            room="7А",
            ticket="1",
            starts_at=base,
        )
        conflicts = await events_service.find_conflicts(
            creator_id=2,
            room="7А",
            starts_at=base,
        )
        assert conflicts
        conflicts_same_creator = await events_service.find_conflicts(
            creator_id=1,
            room="8Б",
            starts_at=base,
        )
        assert conflicts_same_creator

    asyncio.run(scenario())
