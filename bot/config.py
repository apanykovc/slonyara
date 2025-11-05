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
    lead_times: Tuple[int, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class BotSettings:
    """General bot runtime settings."""

    token: str
    admins: Tuple[int, ...] = field(default_factory=tuple)
    admin_usernames: Tuple[str, ...] = field(default_factory=tuple)
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


def _parse_admin_usernames(raw: str | None, *, default: Tuple[str, ...]) -> Tuple[str, ...]:
    if raw is None:
        return tuple(default)
    usernames: list[str] = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip().lstrip("@")
        if not item:
            continue
        usernames.append(item.lower())
    if not usernames:
        return tuple(default)
    return tuple(dict.fromkeys(usernames))


def _parse_lead_times(raw: str | None, *, default: Tuple[int, ...]) -> Tuple[int, ...]:
    if raw is None or not raw.strip():
        return default

    result: list[int] = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip().lower()
        if not token:
            continue
        multiplier = 60
        if token.endswith("h"):
            multiplier = 3600
            token = token[:-1]
        elif token.endswith("m"):
            multiplier = 60
            token = token[:-1]
        elif token.endswith("s"):
            multiplier = 1
            token = token[:-1]
        try:
            value = int(token)
        except ValueError:
            logging.getLogger(__name__).warning("Ignoring invalid reminder lead time: %s", token)
            continue
        if value < 0:
            logging.getLogger(__name__).warning("Lead time cannot be negative: %s", token)
            continue
        result.append(value * multiplier)

    if not result:
        return default

    unique_sorted = sorted(dict.fromkeys(result))
    return tuple(unique_sorted)


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
    admin_usernames = _parse_admin_usernames(
        os.getenv("BOT_ADMIN_USERNAMES"), default=("panykovc",)
    )
    storage_path = Path(os.getenv("BOT_STORAGE_PATH", "data/meetings.db")).expanduser()
    reminder_check_interval = int(os.getenv("BOT_REMINDER_INTERVAL", "60"))
    reminder_lead_times = _parse_lead_times(
        os.getenv("BOT_REMINDER_LEAD"), default=(1800, 600, 0)
    )
    timezone = _load_timezone(os.getenv("BOT_TIMEZONE"))

    storage_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot=BotSettings(token=token, admins=admins, admin_usernames=admin_usernames),
        reminder=ReminderConfig(check_interval=reminder_check_interval, lead_times=reminder_lead_times),
        storage_path=storage_path,
        timezone=timezone,
    )
