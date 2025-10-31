from __future__ import annotations

from typing import Callable, Type, TypeVar

from ..config import BotConfig
from ..storage.base import JsonStorage, SQLiteStorage

T = TypeVar("T")


def create_storage(
    config: BotConfig,
    name: str,
    model: Type[T],
    key_attr: str,
    key_getter: Callable[[dict], str] | None = None,
) -> JsonStorage | SQLiteStorage:
    if config.storage_backend == "sqlite":
        db_path = config.sqlite_path or config.data_dir / "bot.db"
        table = name.replace("-", "_")
        return SQLiteStorage(db_path, table, model, key_attr, key_getter)
    path = config.data_dir / f"{name}.json"
    return JsonStorage(path, model)
