import asyncio
from types import SimpleNamespace

from telegram_meeting_bot.config import NetworkConfig
from telegram_meeting_bot.services.telegram import TelegramSender
from telegram_meeting_bot.utils.metrics import MetricsCollector


def test_safe_tg_call_retries_on_timeout():
    async def scenario():
        network = NetworkConfig()
        metrics = MetricsCollector()
        sender = TelegramSender(bot=SimpleNamespace(), network=network, metrics=metrics)

        attempts = 0

        async def flaky_call(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise asyncio.TimeoutError()
            return "ok"

        async def pump():
            for _ in range(5):
                await asyncio.sleep(0)
                await sender.worker_tick()
                await asyncio.sleep(0.05)

        task = asyncio.create_task(sender.safe_tg_call("ui", "op", flaky_call))
        await pump()
        result = await task
        assert result == "ok"
        assert attempts == 2

    asyncio.run(scenario())
