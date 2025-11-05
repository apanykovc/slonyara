"""Command line entry point for the project."""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Sequence

from dotenv import load_dotenv

from bot.config import load_config
from slonyara.logging_config import setup_logging, get_category_logger

from .app import create_storage, run_bot


_LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Slonyara Telegram assistant")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the bot (default)")
    run_parser.set_defaults(command="run")

    migrate_parser = subparsers.add_parser(
        "migrate", help="Apply database migrations and exit"
    )
    migrate_parser.set_defaults(command="migrate")

    parser.set_defaults(command="run")
    return parser


def _run_migrations() -> None:
    load_dotenv()
    config = load_config()
    schema_logger = get_category_logger("schema")
    schema_logger.info("Ensuring schema for %s", config.storage_path)
    storage = create_storage(config)
    try:
        schema_logger.info("Database ready at %s", config.storage_path)
    finally:
        storage.close()


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        _run_migrations()
        return 0

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        _LOGGER.info("Interrupted, shutting down")
    return 0


__all__ = ["main"]
