from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BotConfig:
    token: str
    data_dir: Path
    logs_dir: Path
    default_lead_time_minutes: int = 30
    scheduler_tick_seconds: int = 30
    timezone: str = "UTC"
    storage_backend: str = "json"
    sqlite_path: Path | None = None


@dataclass(slots=True)
class NetworkConfig:
    request_timeout: float = 10.0
    connect_timeout: float = 5.0
    max_retries: int = 3
    retry_backoff: float = 2.0
    ui_retries: int = 2
    ui_connect_timeout: float = 5.0
    ui_read_timeout: float = 5.0
    ui_jitter_min: float = 0.2
    ui_jitter_max: float = 0.6
    heavy_max_retries: int = 5
    heavy_backoff_start: float = 1.0
    heavy_backoff_cap: float = 15.0


@dataclass(slots=True)
class Config:
    bot: BotConfig
    network: NetworkConfig


def load_config() -> Config:
    token = os.environ.get(
        "BOT_TOKEN",
        "8338879451:AAGTkri6ZXXD88eLAbuOIIqLSVHCoNabVrU",
    )

    base_dir = Path(os.environ.get("BOT_BASE_DIR", Path.cwd()))
    data_dir = Path(os.environ.get("BOT_DATA_DIR", base_dir / "data"))
    logs_dir = Path(os.environ.get("BOT_LOG_DIR", base_dir / "logs"))

    default_lead = int(os.environ.get("BOT_DEFAULT_LEAD_MINUTES", "30"))
    tick = int(os.environ.get("BOT_SCHEDULER_TICK", "30"))
    tz = os.environ.get("BOT_TIMEZONE", "UTC")
    storage_backend = os.environ.get("BOT_STORAGE_BACKEND", "json").lower()
    sqlite_path_env = os.environ.get("BOT_SQLITE_PATH")
    sqlite_path = Path(sqlite_path_env) if sqlite_path_env else None

    bot_config = BotConfig(
        token=token,
        data_dir=data_dir,
        logs_dir=logs_dir,
        default_lead_time_minutes=default_lead,
        scheduler_tick_seconds=tick,
        timezone=tz,
        storage_backend=storage_backend,
        sqlite_path=sqlite_path,
    )
    network_config = NetworkConfig()
    return Config(bot=bot_config, network=network_config)
