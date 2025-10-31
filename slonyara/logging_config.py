"""Logging configuration helpers.

This module centralises logging configuration for the project. It
provides:

* A ``setup_logging`` helper to configure console and file handlers.
* Category-aware loggers via ``get_category_logger``.
* Console output that highlights categories with colours.
* JSON-formatted log files for easier parsing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from logging import LogRecord
from typing import Dict, Tuple

# -- Public API -----------------------------------------------------------------

#: Supported log categories that should be used across the code base.
CATEGORIES: Tuple[str, ...] = ("meeting_created", "reminder_sent", "error")


@dataclass(frozen=True)
class _Colour:
    """ANSI colour fragments used for console output."""

    prefix: str
    suffix: str = "\x1b[0m"

    def wrap(self, value: str) -> str:
        return f"{self.prefix}{value}{self.suffix}"


_CATEGORY_COLOURS: Dict[str, _Colour] = {
    "meeting_created": _Colour("\x1b[38;5;39m"),  # Blue
    "reminder_sent": _Colour("\x1b[38;5;70m"),     # Green
    "error": _Colour("\x1b[38;5;196m"),           # Red
}


class _ConsoleFormatter(logging.Formatter):
    """Format console log records with category labels and colours."""

    def __init__(self) -> None:
        super().__init__("%(message)s")

    def format(self, record: LogRecord) -> str:  # noqa: D401 (short description inherited)
        category = getattr(record, "category", "general")
        colour = _CATEGORY_COLOURS.get(category)
        label = f"[{category}]"
        if colour and _supports_colour():
            label = colour.wrap(label)
        message = super().format(record)
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        parts = [timestamp, level, label, message]
        if record.exc_info:
            parts.append(self.formatException(record.exc_info))
        return " ".join(parts)


class _JsonFormatter(logging.Formatter):
    """Render log records as JSON objects."""

    def format(self, record: LogRecord) -> str:  # noqa: D401 (short description inherited)
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "category": getattr(record, "category", "general"),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _supports_colour() -> bool:
    """Return ``True`` if ANSI colours should be used."""

    target = sys.stdout
    return getattr(target, "isatty", lambda: False)()


def setup_logging(
    *,
    log_file: str = "logs/app.log",
    console_level: int = logging.INFO,
    file_level: int = logging.INFO,
    force: bool = True,
) -> None:
    """Configure logging handlers for console and file output.

    Parameters
    ----------
    log_file:
        Destination path for JSON log output. Parent directories are
        created automatically.
    console_level:
        Logging level for the console handler.
    file_level:
        Logging level for the file handler.
    force:
        If ``True``, remove any pre-existing handlers on the root logger
        before adding new ones.
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(_ConsoleFormatter())

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(_JsonFormatter())

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def get_category_logger(category: str) -> logging.LoggerAdapter:
    """Return a logger adapter that injects the desired category.

    Parameters
    ----------
    category:
        One of :data:`CATEGORIES`. A ``ValueError`` is raised for
        unsupported categories to ensure consistency across the project.
    """

    if category not in CATEGORIES:
        raise ValueError(f"Unsupported log category: {category!r}")

    logger = logging.getLogger(category)
    return logging.LoggerAdapter(logger, {"category": category})
