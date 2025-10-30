from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Type, TypeVar


T = TypeVar("T")


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(val) for key, val in value.items()}
    return value


def _deserialize(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, list):
        return [_deserialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _deserialize(val) for key, val in value.items()}
    return value


class JsonStorage:
    def __init__(self, path: Path, model: Type[T]) -> None:
        self._path = path
        self._model = model
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def load_all(self) -> list[T]:
        async with self._lock:
            if not self._path.exists():
                return []
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [self._model(**_deserialize(item)) for item in data]

    async def save_all(self, items: Iterable[T]) -> None:
        async with self._lock:
            payload: list[dict[str, Any]] = []
            for item in items:
                if is_dataclass(item):
                    payload.append(_serialize(asdict(item)))  # type: ignore[arg-type]
                else:
                    payload.append(_serialize(dict(item)))  # type: ignore[arg-type]
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)

    async def update(self, items: list[T]) -> None:
        await self.save_all(items)

    def __aiter__(self):
        raise TypeError("JsonStorage is not an async iterable")


class SQLiteStorage:
    def __init__(
        self,
        path: Path,
        table: str,
        model: Type[T],
        key_attr: str,
        key_getter: Callable[[Any], str] | None = None,
    ) -> None:
        self._path = path
        self._table = table
        self._model = model
        self._key_attr = key_attr
        self._key_getter = key_getter
        self._lock = asyncio.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} (\n"
                "    key TEXT PRIMARY KEY,\n"
                "    payload TEXT NOT NULL\n"
                ")"
            )
            conn.commit()

    async def load_all(self) -> list[T]:
        async with self._lock:
            rows = await asyncio.to_thread(self._fetch_rows)
        return [self._model(**_deserialize(json.loads(row))) for row in rows]

    def _fetch_rows(self) -> list[str]:
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(f"SELECT payload FROM {self._table}")
            return [row[0] for row in cursor.fetchall()]

    async def save_all(self, items: Iterable[T]) -> None:
        records: list[tuple[str, str]] = []
        for item in items:
            if is_dataclass(item):
                data = asdict(item)
            else:
                data = dict(item)  # type: ignore[arg-type]
            key = self._extract_key(data)
            payload = json.dumps(_serialize(data), ensure_ascii=False)
            records.append((key, payload))
        async with self._lock:
            await asyncio.to_thread(self._write_rows, records)

    def _write_rows(self, records: list[tuple[str, str]]) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(f"DELETE FROM {self._table}")
            conn.executemany(
                f"INSERT OR REPLACE INTO {self._table} (key, payload) VALUES (?, ?)", records
            )
            conn.commit()

    async def update(self, items: list[T]) -> None:
        await self.save_all(items)

    def __aiter__(self):
        raise TypeError("SQLiteStorage is not an async iterable")

    def _extract_key(self, data: dict[str, Any]) -> str:
        if self._key_getter:
            return self._key_getter(data)
        return str(data[self._key_attr])
