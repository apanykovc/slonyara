"""Application configuration helpers for the Telegram bot."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when application configuration is invalid."""


def _read_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:  # pragma: no cover - configuration errors
            raise ConfigError(f"{name} must be an integer") from exc
    if min_value is not None and value < min_value:
        raise ConfigError(f"{name} must be >= {min_value}")
    return value


def _read_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:  # pragma: no cover - configuration errors
            raise ConfigError(f"{name} must be a number") from exc
    if min_value is not None and value < min_value:
        raise ConfigError(f"{name} must be >= {min_value}")
    return value


@dataclass(slots=True)
class RetryConfig:
    """Retry parameters for reminder delivery."""

    attempts: int = 3
    delay: float = 5.0
    max_delay: float = 60.0
    jitter: float = 0.3


@dataclass(slots=True)
class TimeoutConfig:
    """Timeouts for Telegram Bot API requests."""

    ui: float = 5.0
    background: float = 15.0


@dataclass(slots=True)
class ReminderConfig:
    """Configuration for reminder service behaviour."""

    check_interval: int = 60
    lead_times: Tuple[int, ...] = field(default_factory=tuple)
    default_lead_time: int = 900
    retry: RetryConfig = field(default_factory=RetryConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)


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
    locale: str


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
            _logger.warning("Ignoring invalid admin id: %s", item)
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
            _logger.warning("Ignoring invalid reminder lead time: %s", token)
            continue
        if value < 0:
            _logger.warning("Lead time cannot be negative: %s", token)
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
        _logger.warning("Unknown timezone %s, falling back to UTC", name)
        return ZoneInfo("UTC")


def _resolve_default_lead(lead_times: Tuple[int, ...], *, fallback: int) -> int:
    if not lead_times:
        return max(0, fallback)
    positives = [value for value in lead_times if value > 0]
    if positives:
        return max(positives)
    return max(0, max(lead_times))


def _format_seconds_int(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        if remainder:
            return f"{minutes}m {remainder}s"
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if remainder:
        parts.append(f"{remainder}s")
    return " ".join(parts) if parts else f"{seconds}s"


def _format_interval(value: float) -> str:
    rounded = int(round(value))
    if abs(value - rounded) < 1e-3:
        return _format_seconds_int(max(0, rounded))
    return f"{value:.2f}s"


def _format_lead_times(values: Tuple[int, ...]) -> str:
    if not values:
        return "—"
    return ", ".join(_format_seconds_int(max(0, int(v))) for v in values)


def _validate_config(config: Config) -> None:
    if not config.bot.token:
        raise ConfigError("BOT_TOKEN must not be empty")
    if config.storage_path.exists() and config.storage_path.is_dir():
        raise ConfigError("DB_PATH must point to a file path")
    if not config.locale:
        raise ConfigError("LOCALE must not be empty")
    if config.reminder.check_interval <= 0:
        raise ConfigError("SCHED_REMINDER_REFRESH must be greater than zero")
    if config.reminder.default_lead_time < 0:
        raise ConfigError("DEFAULT_LEAD must not be negative")
    if any(value < 0 for value in config.reminder.lead_times):
        raise ConfigError("DEFAULT_LEAD contains negative values")
    if config.reminder.retry.attempts < 1:
        raise ConfigError("RETRY_ATTEMPTS must be greater than zero")
    if config.reminder.retry.delay <= 0:
        raise ConfigError("RETRY_DELAY must be greater than zero")
    if config.reminder.retry.max_delay < config.reminder.retry.delay:
        raise ConfigError("RETRY_MAX_DELAY must be greater than or equal to RETRY_DELAY")
    if config.reminder.retry.jitter < 0:
        raise ConfigError("RETRY_JITTER must not be negative")
    if config.reminder.timeouts.ui <= 0 or config.reminder.timeouts.background <= 0:
        raise ConfigError("UI timeouts must be greater than zero")


def _log_summary(config: Config) -> None:
    timezone_name = getattr(config.timezone, "key", str(config.timezone))
    retry = config.reminder.retry
    timeouts = config.reminder.timeouts
    _logger.info(
        "Configuration loaded: db=%s, locale=%s, timezone=%s, default lead=%s, lead times=[%s], refresh=%s, retries=%sx (delay=%s, max=%s, jitter=%.2f), timeouts ui=%s / background=%s",
        config.storage_path,
        config.locale,
        timezone_name,
        _format_seconds_int(max(0, int(config.reminder.default_lead_time))),
        _format_lead_times(config.reminder.lead_times),
        _format_seconds_int(max(0, int(config.reminder.check_interval))),
        retry.attempts,
        _format_interval(retry.delay),
        _format_interval(retry.max_delay),
        retry.jitter,
        _format_interval(timeouts.ui),
        _format_interval(timeouts.background),
    )


def load_config() -> Config:
    """Load configuration from environment variables."""

    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN environment variable must be set")

    admins = _parse_admins(os.getenv("BOT_ADMINS"))
    admin_usernames = _parse_admin_usernames(
        os.getenv("BOT_ADMIN_USERNAMES"), default=("panykovc",)
    )

    storage_raw = os.getenv("DB_PATH") or os.getenv("BOT_STORAGE_PATH") or "data/meetings.db"
    storage_path = Path(storage_raw).expanduser()

    default_leads = _parse_lead_times(
        os.getenv("DEFAULT_LEAD") or os.getenv("BOT_REMINDER_LEAD"),
        default=(1800, 600, 0),
    )
    fallback_interval = _read_int("BOT_REMINDER_INTERVAL", 60, min_value=1)
    reminder_check_interval = _read_int(
        "SCHED_REMINDER_REFRESH", fallback_interval, min_value=1
    )

    retry = RetryConfig(
        attempts=_read_int("RETRY_ATTEMPTS", 3, min_value=1),
        delay=_read_float("RETRY_DELAY", 5.0, min_value=0.01),
        max_delay=_read_float("RETRY_MAX_DELAY", 60.0, min_value=0.01),
        jitter=_read_float("RETRY_JITTER", 0.3, min_value=0.0),
    )
    timeouts = TimeoutConfig(
        ui=_read_float("UI_TIMEOUT", 5.0, min_value=0.01),
        background=_read_float("UI_BACKGROUND", 15.0, min_value=0.01),
    )

    timezone = _load_timezone(os.getenv("TZ") or os.getenv("BOT_TIMEZONE"))
    locale = (os.getenv("LOCALE") or "ru_RU").strip() or "ru_RU"
    default_lead_time = _resolve_default_lead(default_leads, fallback=900)

    storage_path.parent.mkdir(parents=True, exist_ok=True)

    config = Config(
        bot=BotSettings(
            token=token,
            admins=admins,
            admin_usernames=admin_usernames,
        ),
        reminder=ReminderConfig(
            check_interval=reminder_check_interval,
            lead_times=default_leads,
            default_lead_time=default_lead_time,
            retry=retry,
            timeouts=timeouts,
        ),
        storage_path=storage_path,
        timezone=timezone,
        locale=locale,
    )

    _validate_config(config)
    _log_summary(config)

    return config
