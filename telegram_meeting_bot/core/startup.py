from __future__ import annotations

from .application import Application
from ..config import load_config


async def create_application() -> Application:
    config = load_config()
    return Application(config=config)
