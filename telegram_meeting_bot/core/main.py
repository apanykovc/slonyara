from __future__ import annotations

import asyncio
import logging

from .startup import create_application


def run() -> None:
    """Entry point for launching the bot."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_async_run())


async def _async_run() -> None:
    app = await create_application()
    await app.run()
