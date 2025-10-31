"""Application configuration helpers for the Telegram bot."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(slots=True)
class ReminderConfig:
    """Configuration for reminder service behaviour."""

    check_interval: int = 60
    lead_time: int = 600


@dataclass(slots=True)
class BotSettings:
    """General bot runtime settings."""

    token: str
    admins: Tuple[int, ...] = field(default_factory=tuple)
    default_role: str = "user"
    admin_role: str = "admin"
    parse_mode: str = "HTML"


@dataclass(slots=True)
class Config:
    """Container for application configuration."""

    bot: BotSettings
    reminder: ReminderConfig
    storage_path: Path
    timezone: ZoneInfo


def _parse_admins(raw: str | None) -> Tuple[int, ...]:
    if not raw:
        return tuple()
    admins: list[int] = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            admins.append(int(item))
        except ValueError:
            logging.getLogger(__name__).warning("Ignoring invalid admin id: %s", item)
    return tuple(admins)


def _load_timezone(name: str | None) -> ZoneInfo:
    if not name:
        name = "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logging.getLogger(__name__).warning("Unknown timezone %s, falling back to UTC", name)
        return ZoneInfo("UTC")


def load_config() -> Config:
    """Load configuration from environment variables."""

    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable must be set")

    admins = _parse_admins(os.getenv("BOT_ADMINS"))
    storage_path = Path(os.getenv("BOT_STORAGE_PATH", "data/meetings.json")).expanduser()
    reminder_check_interval = int(os.getenv("BOT_REMINDER_INTERVAL", "60"))
    reminder_lead_time = int(os.getenv("BOT_REMINDER_LEAD", "600"))
    timezone = _load_timezone(os.getenv("BOT_TIMEZONE"))

    storage_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot=BotSettings(token=token, admins=admins),
        reminder=ReminderConfig(check_interval=reminder_check_interval, lead_time=reminder_lead_time),
        storage_path=storage_path,
        timezone=timezone,
    )
