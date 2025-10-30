from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 50 * 1024 * 1024


class SizeAndTimeRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate logs daily or when size limit exceeded."""

    def __init__(self, filename: Path, backup_count: int) -> None:
        filename.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(filename, when="midnight", interval=1, backupCount=backup_count, encoding="utf-8")

    def shouldRollover(self, record: logging.LogRecord) -> int:  # noqa: N802 - signature from base class
        rollover = super().shouldRollover(record)
        if rollover:
            return 1
        if self.stream is None:
            self.stream = self._open()
        if self.stream.tell() + len(self.format(record).encode("utf-8")) >= MAX_BYTES:
            return 1
        return 0


def setup_logging(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

    app_log = SizeAndTimeRotatingFileHandler(base_dir / "app" / "app.log", backup_count=14)
    err_log = SizeAndTimeRotatingFileHandler(base_dir / "error" / "error.log", backup_count=30)
    audit_log = SizeAndTimeRotatingFileHandler(base_dir / "audit" / "audit.log", backup_count=14)

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    app_logger = logging.getLogger("telegram_meeting_bot")
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(app_log)

    error_logger = logging.getLogger("telegram_meeting_bot.error")
    error_logger.setLevel(logging.WARNING)
    error_logger.addHandler(err_log)

    audit_logger = logging.getLogger("telegram_meeting_bot.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.addHandler(audit_log)

    logging.getLogger("apscheduler").setLevel(logging.INFO)
