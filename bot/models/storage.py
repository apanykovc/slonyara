"""Persistence layer for meetings and bot settings backed by SQLite."""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, NamedTuple, Optional, Sequence, Tuple, cast
from uuid import uuid4

from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)

RoleName = Literal["admin", "user"]
_VALID_ROLES: Tuple[RoleName, ...] = ("admin", "user")


def _normalize_role(value: Any) -> RoleName | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _VALID_ROLES:
        return cast(RoleName, text)
    return None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_tz(dt: datetime, tz: ZoneInfo | None) -> datetime:
    if dt.tzinfo is None:
        if tz is not None:
            return dt.replace(tzinfo=tz)
        return dt.replace(tzinfo=timezone.utc)
    if tz is None:
        return dt
    return dt.astimezone(tz)


@dataclass(slots=True)
class Meeting:
    """Data container that represents a planned meeting."""

    id: str
    title: str
    scheduled_at: datetime
    organizer_id: int
    participants: List[int] = field(default_factory=list)
    description: Optional[str] = None
    reminder_sent: bool = False
    meeting_type: Optional[str] = None
    room: Optional[str] = None
    request_number: Optional[str] = None
    chat_id: Optional[int] = None
    status: str = "planned"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "scheduled_at": self.scheduled_at.isoformat(),
            "organizer_id": self.organizer_id,
            "participants": self.participants,
            "description": self.description,
            "reminder_sent": self.reminder_sent,
            "meeting_type": self.meeting_type,
            "room": self.room,
            "request_number": self.request_number,
            "chat_id": self.chat_id,
            "status": self.status,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Meeting":
        scheduled = datetime.fromisoformat(payload["scheduled_at"])
        created_at_raw = payload.get("created_at")
        updated_at_raw = payload.get("updated_at")
        created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
        updated_at = datetime.fromisoformat(updated_at_raw) if updated_at_raw else None
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title", "")),
            scheduled_at=scheduled,
            organizer_id=int(payload.get("organizer_id", 0)),
            participants=[int(pid) for pid in payload.get("participants", [])],
            description=payload.get("description"),
            reminder_sent=bool(payload.get("reminder_sent", False)),
            meeting_type=payload.get("meeting_type"),
            room=payload.get("room"),
            request_number=payload.get("request_number"),
            chat_id=payload.get("chat_id"),
            status=str(payload.get("status", "planned")),
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(slots=True)
class ChatSettings:
    """Persistent settings and permissions for a chat."""

    id: int
    title: str = ""
    lead_times: List[int] = field(default_factory=list)
    admin_ids: List[int] = field(default_factory=list)
    roles: Dict[int, RoleName] = field(default_factory=dict)
    reminder_log: Dict[str, List[int]] = field(default_factory=dict)
    timezone: Optional[str] = None
    default_lead: Optional[int] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "lead_times": self.lead_times,
            "admin_ids": self.admin_ids,
            "roles": {str(user_id): role for user_id, role in self.roles.items()},
            "reminder_log": self.reminder_log,
            "timezone": self.timezone,
            "default_lead": self.default_lead,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ChatSettings":
        lead_times: list[int] = []
        for value in payload.get("lead_times", []) or []:
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                continue
            if seconds < 0:
                continue
            lead_times.append(seconds)
        admin_ids: list[int] = []
        for value in payload.get("admin_ids", []) or []:
            try:
                admin_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        roles_payload = payload.get("roles", {}) or {}
        roles: dict[int, RoleName] = {}
        for raw_user_id, raw_role in roles_payload.items():
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue
            role = _normalize_role(raw_role)
            if role is None:
                continue
            roles[user_id] = role
        for admin_id in admin_ids:
            roles.setdefault(admin_id, "admin")
        for user_id, role in list(roles.items()):
            if role == "admin" and user_id not in admin_ids:
                admin_ids.append(user_id)
        admin_ids = list(dict.fromkeys(admin_ids))
        reminder_log: dict[str, list[int]] = {}
        for key, values in (payload.get("reminder_log", {}) or {}).items():
            normalized: list[int] = []
            for value in values:
                try:
                    normalized.append(int(value))
                except (TypeError, ValueError):
                    continue
            reminder_log[str(key)] = normalized
        return cls(
            id=int(payload["id"]),
            title=str(payload.get("title", "")),
            lead_times=lead_times,
            admin_ids=admin_ids,
            roles=roles,
            reminder_log=reminder_log,
            timezone=payload.get("timezone"),
            default_lead=payload.get("default_lead"),
            is_active=bool(payload.get("is_active", True)),
        )


@dataclass(slots=True)
class UserSettings:
    """Persistent preferences for an individual user."""

    id: int
    timezone: Optional[str] = None
    locale: str = "ru_RU"
    date_format: str = "%d.%m.%Y"
    time_format: str = "%H:%M"
    default_lead_time: int = 900
    role: RoleName = "user"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "timezone": self.timezone,
            "locale": self.locale,
            "date_format": self.date_format,
            "time_format": self.time_format,
            "default_lead_time": self.default_lead_time,
            "role": self.role,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UserSettings":
        timezone_value = payload.get("timezone")
        if timezone_value:
            timezone_value = str(timezone_value)
        default_lead_time = payload.get("default_lead_time", 900)
        try:
            default_lead_time = int(default_lead_time)
        except (TypeError, ValueError):
            default_lead_time = 900
        if default_lead_time < 0:
            default_lead_time = 0
        created_at_raw = payload.get("created_at")
        updated_at_raw = payload.get("updated_at")
        created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
        updated_at = datetime.fromisoformat(updated_at_raw) if updated_at_raw else None
        role = _normalize_role(payload.get("role")) or "user"
        return cls(
            id=int(payload.get("id", 0)),
            timezone=timezone_value,
            locale=str(payload.get("locale", "ru_RU")),
            date_format=str(payload.get("date_format", "%d.%m.%Y")),
            time_format=str(payload.get("time_format", "%H:%M")),
            default_lead_time=default_lead_time,
            role=role,
            created_at=created_at,
            updated_at=updated_at,
        )


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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_scheduled_at ON meetings(scheduled_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_meeting ON reminders(meeting_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_roles_user ON chat_roles(user_id)")


def _downgrade_v1(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_chat_roles_user")
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


class MeetingStorage:
    """SQLite-backed storage implementation."""

    def __init__(
        self,
        path: Path,
        timezone: ZoneInfo | None = None,
        *,
        default_lead_times: Sequence[int] | None = None,
        default_user_lead_time: int | None = None,
        default_locale: str | None = None,
    ) -> None:
        self._path = path
        self._timezone = timezone
        self._default_lead_times: tuple[int, ...] = tuple(default_lead_times or ())
        if default_user_lead_time is None:
            default_user_lead_time = 900
        self._default_user_lead_time = max(0, int(default_user_lead_time))
        self._default_locale = (default_locale or "ru_RU").strip() or "ru_RU"
        self._default_timezone_name = (
            getattr(self._timezone, "key", str(self._timezone)) if self._timezone else None
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON")
        self._apply_migrations()

    @property
    def timezone(self) -> ZoneInfo | None:
        """Return configured timezone, if any."""

        return self._timezone

    # ------------------------------------------------------------------
    # migration helpers
    def _get_schema_version(self) -> int:
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
                return 0
            return int(row[0])

    def _set_schema_version(self, version: int) -> None:
        cur = self._conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cur.fetchone()[0]
        if count:
            self._conn.execute("UPDATE schema_version SET version = ?", (version,))
        else:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _apply_migrations(self) -> None:
        with self._lock:
            current = self._get_schema_version()
            target = MIGRATIONS[-1].version if MIGRATIONS else 0
            if current < target:
                for migration in MIGRATIONS:
                    if migration.version > current:
                        _logger.info("Applying migration %s", migration.version)
                        with self._conn:
                            migration.upgrade(self._conn)
                            self._set_schema_version(migration.version)
                        current = migration.version
                _logger.info("Schema migrated to version %s", target)
            elif current > target:
                for migration in reversed(MIGRATIONS):
                    if migration.version <= current:
                        _logger.info("Reverting migration %s", migration.version)
                        with self._conn:
                            migration.downgrade(self._conn)
                            self._set_schema_version(migration.version - 1)
                        current = migration.version - 1
                _logger.info("Schema downgraded to version %s", target)

    # ------------------------------------------------------------------
    # meeting management
    def list_meetings(self) -> List[Meeting]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM meetings WHERE status != 'canceled' ORDER BY scheduled_at"
            ).fetchall()
        return [self._row_to_meeting(row) for row in rows]

    def list_meetings_for_user(self, user_id: int, *, chat_id: Optional[int] = None) -> List[Meeting]:
        query = [
            "SELECT m.* FROM meetings m",
            "JOIN meeting_participants p ON m.id = p.meeting_id",
            "WHERE p.user_id = ? AND m.status != 'canceled'",
        ]
        params: list[Any] = [int(user_id)]
        if chat_id is not None:
            query.append("AND m.chat_id = ?")
            params.append(int(chat_id))
        query.append("ORDER BY m.scheduled_at")
        sql = " ".join(query)
        with self._lock, self._conn:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_meeting(row) for row in rows]

    def list_meetings_for_chat(self, chat_id: int) -> List[Meeting]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM meetings WHERE chat_id = ? AND status != 'canceled' ORDER BY scheduled_at",
                (int(chat_id),),
            ).fetchall()
        return [self._row_to_meeting(row) for row in rows]

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE id = ?",
                (meeting_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_meeting(row)

    def find_meeting_by_request_number(self, request_number: str) -> Optional[Meeting]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE ticket_no = ? AND status != 'canceled'",
                (request_number,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_meeting(row)

    def create_meeting(
        self,
        title: str,
        scheduled_at: datetime,
        organizer_id: int,
        participants: Optional[Iterable[int]] = None,
        description: Optional[str] = None,
        *,
        meeting_type: Optional[str] = None,
        room: Optional[str] = None,
        request_number: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> Meeting:
        normalized_dt = _ensure_tz(scheduled_at, self._timezone)
        normalized_dt = normalized_dt.astimezone(self._timezone or normalized_dt.tzinfo or timezone.utc)
        utc_dt = normalized_dt.astimezone(timezone.utc)
        scheduled_iso = normalized_dt.isoformat(timespec="seconds")
        date_utc = utc_dt.date().isoformat()
        time_utc = utc_dt.time().isoformat(timespec="seconds")
        meeting_id = str(uuid4())
        created_at = _utcnow()
        participant_ids = list(dict.fromkeys(int(pid) for pid in (participants or [organizer_id])))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO meetings (
                    id, chat_id, creator_user_id, title, description, scheduled_at,
                    date_utc, start_time_utc, type, room, ticket_no, status,
                    reminder_sent, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', 0, ?, ?)
                """,
                (
                    meeting_id,
                    int(chat_id) if chat_id is not None else None,
                    int(organizer_id),
                    title,
                    description,
                    scheduled_iso,
                    date_utc,
                    time_utc,
                    meeting_type,
                    room,
                    request_number,
                    created_at,
                    created_at,
                ),
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO meeting_participants (meeting_id, user_id) VALUES (?, ?)",
                [(meeting_id, pid) for pid in participant_ids],
            )
        meeting = Meeting(
            id=meeting_id,
            title=title,
            scheduled_at=normalized_dt,
            organizer_id=int(organizer_id),
            participants=participant_ids,
            description=description,
            meeting_type=meeting_type,
            room=room,
            request_number=request_number,
            chat_id=chat_id,
            reminder_sent=False,
            status="planned",
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(created_at),
        )
        return meeting

    def cancel_meeting(self, meeting_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE meetings SET status = 'canceled', updated_at = ? WHERE id = ?",
                (_utcnow(), meeting_id),
            )
            if cur.rowcount:
                self._conn.execute(
                    "DELETE FROM chat_reminder_log WHERE meeting_id = ?",
                    (meeting_id,),
                )
                return True
        return False

    def reschedule_meeting(self, meeting_id: str, scheduled_at: datetime) -> bool:
        normalized_dt = _ensure_tz(scheduled_at, self._timezone)
        normalized_dt = normalized_dt.astimezone(self._timezone or normalized_dt.tzinfo or timezone.utc)
        utc_dt = normalized_dt.astimezone(timezone.utc)
        scheduled_iso = normalized_dt.isoformat(timespec="seconds")
        date_utc = utc_dt.date().isoformat()
        time_utc = utc_dt.time().isoformat(timespec="seconds")
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                UPDATE meetings
                SET scheduled_at = ?, date_utc = ?, start_time_utc = ?,
                    status = 'moved', reminder_sent = 0, updated_at = ?
                WHERE id = ?
                """,
                (scheduled_iso, date_utc, time_utc, _utcnow(), meeting_id),
            )
            if cur.rowcount:
                self._conn.execute(
                    "DELETE FROM chat_reminder_log WHERE meeting_id = ?",
                    (meeting_id,),
                )
                return True
        return False

    def update_meeting(
        self,
        meeting_id: str,
        *,
        title: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
        meeting_type: Optional[str] = None,
        room: Optional[str] = None,
        request_number: Optional[str] = None,
    ) -> Optional[Meeting]:
        fields: list[str] = []
        params: list[Any] = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if meeting_type is not None:
            fields.append("type = ?")
            params.append(meeting_type)
        if room is not None:
            fields.append("room = ?")
            params.append(room)
        if request_number is not None:
            fields.append("ticket_no = ?")
            params.append(request_number)
        if scheduled_at is not None:
            normalized_dt = _ensure_tz(scheduled_at, self._timezone)
            normalized_dt = normalized_dt.astimezone(self._timezone or normalized_dt.tzinfo or timezone.utc)
            utc_dt = normalized_dt.astimezone(timezone.utc)
            fields.append("scheduled_at = ?")
            params.append(normalized_dt.isoformat(timespec="seconds"))
            fields.append("date_utc = ?")
            params.append(utc_dt.date().isoformat())
            fields.append("start_time_utc = ?")
            params.append(utc_dt.time().isoformat(timespec="seconds"))
            fields.append("reminder_sent = 0")
            fields.append("status = 'moved'")
        if not fields:
            return self.get_meeting(meeting_id)
        fields.append("updated_at = ?")
        params.append(_utcnow())
        params.append(meeting_id)
        sql = "UPDATE meetings SET " + ", ".join(fields) + " WHERE id = ?"
        with self._lock, self._conn:
            cur = self._conn.execute(sql, params)
            if not cur.rowcount:
                return None
            if scheduled_at is not None:
                self._conn.execute(
                    "DELETE FROM chat_reminder_log WHERE meeting_id = ?",
                    (meeting_id,),
                )
        return self.get_meeting(meeting_id)

    def mark_reminder_sent(self, meeting_id: str, chat_id: int, lead_time: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO chat_reminder_log (chat_id, meeting_id, lead_seconds) VALUES (?, ?, ?)",
                (int(chat_id), meeting_id, int(lead_time)),
            )
            if lead_time == 0:
                self._conn.execute(
                    "UPDATE meetings SET reminder_sent = 1, updated_at = ? WHERE id = ?",
                    (_utcnow(), meeting_id),
                )

    def is_reminder_sent(self, meeting_id: str, chat_id: int, lead_time: int) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT 1 FROM chat_reminder_log
                WHERE chat_id = ? AND meeting_id = ? AND lead_seconds = ?
                LIMIT 1
                """,
                (int(chat_id), meeting_id, int(lead_time)),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # chat helpers
    def list_chats(self) -> List[ChatSettings]:
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT * FROM chats").fetchall()
        chats: list[ChatSettings] = []
        for row in rows:
            chats.append(self._row_to_chat_settings(row))
        return chats

    def get_chat(self, chat_id: int) -> Optional[ChatSettings]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM chats WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
        if not row:
            return None
        return self._row_to_chat_settings(row)

    def is_chat_registered(self, chat_id: int) -> bool:
        return self.get_chat(chat_id) is not None

    def get_chat_role(self, chat_id: int, user_id: int) -> Optional[RoleName]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT role FROM chat_roles WHERE chat_id = ? AND user_id = ?",
                (int(chat_id), int(user_id)),
            ).fetchone()
        if not row:
            return None
        return cast(RoleName, row[0]) if row[0] in _VALID_ROLES else None

    def has_chat_role(self, chat_id: int, user_id: int, roles: Iterable[str]) -> bool:
        allowed = {role.strip().lower() for role in roles if role}
        role = self.get_chat_role(chat_id, user_id)
        return role in allowed

    def list_user_chats(
        self, user_id: int, *, roles: Iterable[str] | None = None
    ) -> List[ChatSettings]:
        allowed = {role.strip().lower() for role in roles or [] if role}
        sql = [
            "SELECT c.* FROM chats c",
            "JOIN chat_roles r ON c.chat_id = r.chat_id",
            "WHERE r.user_id = ?",
        ]
        params: list[Any] = [int(user_id)]
        if roles is not None:
            if not allowed:
                return []
            sql.append("AND r.role IN (%s)" % ",".join("?" for _ in allowed))
            params.extend(sorted(allowed))
        sql.append("ORDER BY c.chat_id")
        query = " ".join(sql)
        with self._lock, self._conn:
            rows = self._conn.execute(query, params).fetchall()
        chats: list[ChatSettings] = []
        for row in rows:
            chat = self._row_to_chat_settings(row)
            if roles is None or chat.roles.get(int(user_id)) in allowed:
                chats.append(chat)
        return chats

    def register_chat(
        self,
        chat_id: int,
        title: Optional[str],
        *,
        lead_times: Sequence[int] | None = None,
        admin_ids: Iterable[int] | None = None,
        chat_type: Optional[str] = None,
        timezone: Optional[str] = None,
        default_lead: Optional[int] = None,
    ) -> ChatSettings:
        normalized_leads = self._normalize_lead_times(lead_times or self._default_lead_times or (1800, 600, 0))
        admins: list[int] = []
        for candidate in admin_ids or []:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value not in admins:
                admins.append(value)
        now = _utcnow()
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
            if existing:
                self._conn.execute(
                    """
                    UPDATE chats SET title = COALESCE(?, title), type = COALESCE(?, type),
                        tz = COALESCE(?, tz), default_lead = COALESCE(?, default_lead),
                        updated_at = ?
                    WHERE chat_id = ?
                    """,
                    (title, chat_type, timezone, default_lead, now, int(chat_id)),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO chats (chat_id, type, title, default_lead, tz, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        int(chat_id),
                        chat_type,
                        title,
                        default_lead,
                        timezone,
                        now,
                        now,
                    ),
                )
            self._conn.execute(
                "DELETE FROM chat_lead_times WHERE chat_id = ?",
                (int(chat_id),),
            )
            self._conn.executemany(
                "INSERT INTO chat_lead_times (chat_id, lead_seconds) VALUES (?, ?)",
                [(int(chat_id), lt) for lt in normalized_leads],
            )
            for admin_id in admins:
                self._conn.execute(
                    "INSERT OR REPLACE INTO chat_roles (chat_id, user_id, role) VALUES (?, ?, 'admin')",
                    (int(chat_id), int(admin_id)),
                )
        chat = self.get_chat(chat_id)
        if chat is None:
            raise RuntimeError("Failed to register chat")
        return chat

    def set_chat_lead_times(self, chat_id: int, lead_times: Sequence[int]) -> Optional[ChatSettings]:
        normalized = self._normalize_lead_times(lead_times)
        if not normalized:
            return None
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
            if not exists:
                return None
            self._conn.execute(
                "DELETE FROM chat_lead_times WHERE chat_id = ?",
                (int(chat_id),),
            )
            self._conn.executemany(
                "INSERT INTO chat_lead_times (chat_id, lead_seconds) VALUES (?, ?)",
                [(int(chat_id), lt) for lt in normalized],
            )
            self._conn.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?",
                (_utcnow(), int(chat_id)),
            )
        return self.get_chat(chat_id)

    def add_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        return self.set_chat_role(chat_id, user_id, "admin")

    def remove_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        return self.set_chat_role(chat_id, user_id, "user")

    def set_chat_role(self, chat_id: int, user_id: int, role: str) -> Optional[ChatSettings]:
        normalized_role = _normalize_role(role)
        if normalized_role is None:
            return None
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
            if not exists:
                return None
            self._conn.execute(
                "INSERT OR REPLACE INTO chat_roles (chat_id, user_id, role) VALUES (?, ?, ?)",
                (int(chat_id), int(user_id), normalized_role),
            )
            self._conn.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?",
                (_utcnow(), int(chat_id)),
            )
        return self.get_chat(chat_id)

    def clear_chat_role(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
            if not exists:
                return None
            self._conn.execute(
                "DELETE FROM chat_roles WHERE chat_id = ? AND user_id = ?",
                (int(chat_id), int(user_id)),
            )
            self._conn.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?",
                (_utcnow(), int(chat_id)),
            )
        return self.get_chat(chat_id)

    def is_chat_admin(self, chat_id: int, user_id: int) -> bool:
        return self.get_chat_role(chat_id, user_id) == "admin"

    # ------------------------------------------------------------------
    # settings helpers
    def get_setting(self, name: str, default: Any = None) -> Any:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (name,),
            ).fetchone()
        if not row:
            return default
        return row[0]

    def set_setting(self, name: str, value: Any) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (name, str(value)),
            )

    def get_user_settings(self, user_id: int) -> UserSettings:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        if not row:
            settings = UserSettings(id=int(user_id))
            return self._ensure_user_defaults(settings)
        payload = {
            "id": row["user_id"],
            "timezone": row["tz"],
            "locale": row["locale"],
            "date_format": row["date_format"],
            "time_format": row["time_format"],
            "default_lead_time": row["default_lead"],
            "role": row["role"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        settings = UserSettings.from_dict(payload)
        return self._ensure_user_defaults(settings)

    def save_user_settings(self, settings: UserSettings) -> UserSettings:
        normalized = self._ensure_user_defaults(settings)
        now = _utcnow()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO users (user_id, role, tz, locale, date_format, time_format, default_lead, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role = excluded.role,
                    tz = excluded.tz,
                    locale = excluded.locale,
                    date_format = excluded.date_format,
                    time_format = excluded.time_format,
                    default_lead = excluded.default_lead,
                    updated_at = excluded.updated_at
                """,
                (
                    int(normalized.id),
                    normalized.role,
                    normalized.timezone,
                    normalized.locale,
                    normalized.date_format,
                    normalized.time_format,
                    int(normalized.default_lead_time),
                    now,
                    now,
                ),
            )
        refreshed = self.get_user_settings(normalized.id)
        return refreshed

    def update_user_settings(self, user_id: int, **updates: Any) -> UserSettings:
        current = self.get_user_settings(user_id)
        for field_name, value in updates.items():
            if not hasattr(current, field_name):
                continue
            setattr(current, field_name, value)
        return self.save_user_settings(current)

    # ------------------------------------------------------------------
    def _row_to_meeting(self, row: sqlite3.Row) -> Meeting:
        meeting_id = str(row["id"])
        with self._lock, self._conn:
            participants = self._conn.execute(
                "SELECT user_id FROM meeting_participants WHERE meeting_id = ? ORDER BY user_id",
                (meeting_id,),
            ).fetchall()
        participant_ids = [int(item[0]) for item in participants]
        scheduled = datetime.fromisoformat(row["scheduled_at"])
        scheduled = _ensure_tz(scheduled, self._timezone)
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        updated = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        meeting = Meeting(
            id=meeting_id,
            title=row["title"],
            scheduled_at=scheduled,
            organizer_id=int(row["creator_user_id"]) if row["creator_user_id"] is not None else 0,
            participants=participant_ids,
            description=row["description"],
            reminder_sent=bool(row["reminder_sent"]),
            meeting_type=row["type"],
            room=row["room"],
            request_number=row["ticket_no"],
            chat_id=int(row["chat_id"]) if row["chat_id"] is not None else None,
            status=row["status"],
            created_at=created,
            updated_at=updated,
        )
        return meeting

    def _row_to_chat_settings(self, row: sqlite3.Row) -> ChatSettings:
        chat_id = int(row["chat_id"])
        with self._lock, self._conn:
            leads = self._conn.execute(
                "SELECT lead_seconds FROM chat_lead_times WHERE chat_id = ? ORDER BY lead_seconds",
                (chat_id,),
            ).fetchall()
            roles = self._conn.execute(
                "SELECT user_id, role FROM chat_roles WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
            reminder_entries = self._conn.execute(
                "SELECT meeting_id, lead_seconds FROM chat_reminder_log WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        lead_times = [int(item[0]) for item in leads]
        roles_map: dict[int, RoleName] = {}
        for user_id, role in roles:
            normalized_role = _normalize_role(role)
            if normalized_role is None:
                continue
            roles_map[int(user_id)] = normalized_role
        reminder_log: dict[str, list[int]] = {}
        for meeting_id, lead_seconds in reminder_entries:
            reminder_log.setdefault(str(meeting_id), []).append(int(lead_seconds))
        payload = {
            "id": chat_id,
            "title": row["title"] or "",
            "lead_times": lead_times,
            "roles": {str(user_id): role for user_id, role in roles_map.items()},
            "admin_ids": [user_id for user_id, role in roles_map.items() if role == "admin"],
            "reminder_log": reminder_log,
            "timezone": row["tz"],
            "default_lead": row["default_lead"],
            "is_active": bool(row["is_active"]),
        }
        return self._ensure_chat_defaults(ChatSettings.from_dict(payload))

    def _ensure_chat_defaults(self, chat: ChatSettings) -> ChatSettings:
        if not chat.lead_times:
            default = self._default_lead_times or (1800, 600, 0)
            chat.lead_times = list(default)
        chat.lead_times = self._normalize_lead_times(chat.lead_times)
        if not chat.timezone and self._default_timezone_name:
            chat.timezone = self._default_timezone_name
        normalized_roles: dict[int, RoleName] = {}
        for user_id, role in chat.roles.items():
            try:
                normalized_user = int(user_id)
            except (TypeError, ValueError):
                continue
            normalized_role = _normalize_role(role)
            if normalized_role is None:
                continue
            normalized_roles[normalized_user] = normalized_role
        chat.roles = normalized_roles
        chat.admin_ids = [user_id for user_id, role in chat.roles.items() if role == "admin"]
        chat.reminder_log = {
            meeting_id: self._normalize_lead_times(values)
            for meeting_id, values in chat.reminder_log.items()
        }
        return chat

    def _ensure_user_defaults(self, settings: UserSettings) -> UserSettings:
        if settings.created_at is None:
            settings.default_lead_time = self._default_user_lead_time
        if not settings.locale or settings.created_at is None:
            settings.locale = self._default_locale
        if not settings.timezone and self._default_timezone_name:
            settings.timezone = self._default_timezone_name
        if not settings.date_format:
            settings.date_format = "%d.%m.%Y"
        if not settings.time_format:
            settings.time_format = "%H:%M"
        if settings.default_lead_time < 0:
            settings.default_lead_time = 0
        if settings.role not in _VALID_ROLES:
            settings.role = "user"
        return settings

    def _normalize_lead_times(self, values: Sequence[int] | Iterable[int]) -> List[int]:
        normalized: list[int] = []
        for value in values:
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                continue
            if seconds < 0:
                continue
            normalized.append(seconds)
        if not normalized:
            return []
        return sorted(dict.fromkeys(normalized))

