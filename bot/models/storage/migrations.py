"""Database migrations for the storage layer."""
from __future__ import annotations

import sqlite3
from typing import Callable, NamedTuple, Tuple


class Migration(NamedTuple):
    version: int
    upgrade: Callable[[sqlite3.Connection], None]
    downgrade: Callable[[sqlite3.Connection], None]


def _upgrade_v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user',
            tz TEXT,
            locale TEXT,
            date_format TEXT,
            time_format TEXT,
            default_lead INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            type TEXT,
            title TEXT,
            default_lead INTEGER,
            tz TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            chat_id INTEGER,
            creator_user_id INTEGER,
            title TEXT NOT NULL DEFAULT '',
            description TEXT,
            scheduled_at TEXT NOT NULL,
            date_utc TEXT NOT NULL,
            start_time_utc TEXT NOT NULL,
            type TEXT,
            room TEXT,
            ticket_no TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE SET NULL,
            FOREIGN KEY(creator_user_id) REFERENCES users(user_id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_participants (
            meeting_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (meeting_id, user_id),
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            fire_at TEXT NOT NULL,
            lead_minutes INTEGER NOT NULL,
            sent_at TEXT,
            status TEXT NOT NULL DEFAULT 'scheduled',
            dedup_key TEXT,
            UNIQUE(dedup_key),
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            who_user_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            payload_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS locks (
            key TEXT PRIMARY KEY,
            ttl_until TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_lead_times (
            chat_id INTEGER NOT NULL,
            lead_seconds INTEGER NOT NULL,
            PRIMARY KEY (chat_id, lead_seconds),
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_roles (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            PRIMARY KEY (chat_id, user_id),
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_reminder_log (
            chat_id INTEGER NOT NULL,
            meeting_id TEXT NOT NULL,
            lead_seconds INTEGER NOT NULL,
            PRIMARY KEY (chat_id, meeting_id, lead_seconds),
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_chat_id ON meetings(chat_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_meetings_scheduled_at ON meetings(scheduled_at)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_meeting ON reminders(meeting_id)")


def _downgrade_v1(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_reminders_meeting")
    conn.execute("DROP INDEX IF EXISTS idx_meetings_scheduled_at")
    conn.execute("DROP INDEX IF EXISTS idx_meetings_chat_id")
    conn.execute("DROP TABLE IF EXISTS chat_reminder_log")
    conn.execute("DROP TABLE IF EXISTS chat_roles")
    conn.execute("DROP TABLE IF EXISTS chat_lead_times")
    conn.execute("DROP TABLE IF EXISTS settings")
    conn.execute("DROP TABLE IF EXISTS locks")
    conn.execute("DROP TABLE IF EXISTS audit_logs")
    conn.execute("DROP TABLE IF EXISTS reminders")
    conn.execute("DROP TABLE IF EXISTS meeting_participants")
    conn.execute("DROP TABLE IF EXISTS meetings")
    conn.execute("DROP TABLE IF EXISTS chats")
    conn.execute("DROP TABLE IF EXISTS users")


MIGRATIONS: Tuple[Migration, ...] = (
    Migration(version=1, upgrade=_upgrade_v1, downgrade=_downgrade_v1),
)


__all__ = ["MIGRATIONS", "Migration"]
