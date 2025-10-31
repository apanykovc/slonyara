import asyncio

from telegram_meeting_bot.utils.locks import ClickGuard


def test_click_guard_deduplicates_and_expires():
    async def scenario():
        guard = ClickGuard(window=0.1)
        assert await guard.acquire(1, 1)
        assert not await guard.acquire(1, 1)
        await guard.release(1, 1)
        assert await guard.acquire(1, 1)
        await guard.release(1, 1)
        assert await guard.acquire(1, 1)
        await guard.release_later(1, 1)
        await asyncio.sleep(0.2)
        assert await guard.acquire(1, 1)

    asyncio.run(scenario())
