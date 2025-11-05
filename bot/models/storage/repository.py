"""SQLite-backed storage implementation with audit logging."""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast
from uuid import uuid4

from zoneinfo import ZoneInfo

from slonyara.logging_config import get_category_logger

from .audit import AuditEvent
from .entities import (
    ChatSettings,
    Meeting,
    UserSettings,
    ensure_chat_defaults,
    ensure_user_defaults,
)
from .migrations import MIGRATIONS
from .utils import (
    RoleName,
    ensure_timezone,
    normalize_lead_times,
    normalize_role,
    utcnow,
)


__all__ = ["MeetingStorage"]


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

    def __enter__(self) -> "MeetingStorage":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def timezone(self) -> ZoneInfo | None:
        """Return configured timezone, if any."""

        return self._timezone

    # ------------------------------------------------------------------
    # internal helpers
    def _record_audit(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        payload: Dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> None:
        event = AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or None,
            user_id=user_id,
        )
        self._conn.execute(
            """
            INSERT INTO audit_logs (at, who_user_id, action, entity_type, entity_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            event.as_db_tuple(),
        )
        try:
            logger = get_category_logger(action)
        except ValueError:
            logger = logging.getLogger(action)
        log_payload = payload or {}
        logger.info(
            "%s %s %s",
            action,
            entity_type,
            entity_id or "-",
            extra={"payload": log_payload, "user_id": user_id},
        )

    def _log_schema_change(self, message: str, *args: Any) -> None:
        get_category_logger("schema").info(message, *args)

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
                        self._log_schema_change("Applying migration %s", migration.version)
                        with self._conn:
                            migration.upgrade(self._conn)
                            self._set_schema_version(migration.version)
                        current = migration.version
                self._log_schema_change("Schema migrated to version %s", target)
            elif current > target:
                for migration in reversed(MIGRATIONS):
                    if migration.version <= current:
                        self._log_schema_change("Reverting migration %s", migration.version)
                        with self._conn:
                            migration.downgrade(self._conn)
                            self._set_schema_version(migration.version - 1)
                        current = migration.version - 1
                self._log_schema_change("Schema downgraded to version %s", target)

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

    def find_meeting_by_request_number(self, request_number: str) -> Optional[Meeting]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE ticket_no = ? AND status != 'canceled'",
                (request_number,),
            ).fetchone()
        return self._row_to_meeting(row) if row else None

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE id = ?",
                (meeting_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_meeting(row)

    def create_meeting(
        self,
        *,
        title: str,
        scheduled_at: datetime,
        organizer_id: int,
        participants: Sequence[int],
        description: Optional[str] = None,
        meeting_type: Optional[str] = None,
        room: Optional[str] = None,
        request_number: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> Meeting:
        normalized_dt = ensure_timezone(scheduled_at, self._timezone)
        normalized_dt = normalized_dt.astimezone(
            self._timezone or normalized_dt.tzinfo or timezone.utc
        )
        utc_dt = normalized_dt.astimezone(timezone.utc)
        meeting_id = str(uuid4())
        created_at = utcnow()
        participant_ids = [int(pid) for pid in participants]
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO meetings (
                    id, chat_id, creator_user_id, title, description, scheduled_at,
                    date_utc, start_time_utc, type, room, ticket_no, status,
                    reminder_sent, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', 0, ?, ?)
                """,
                (
                    meeting_id,
                    int(chat_id) if chat_id is not None else None,
                    int(organizer_id),
                    title,
                    description,
                    normalized_dt.isoformat(timespec="seconds"),
                    utc_dt.date().isoformat(),
                    utc_dt.time().isoformat(timespec="seconds"),
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
            self._record_audit(
                action="meeting_created",
                entity_type="meeting",
                entity_id=meeting_id,
                user_id=int(organizer_id),
                payload={
                    "title": title,
                    "scheduled_at": normalized_dt.isoformat(timespec="seconds"),
                    "chat_id": chat_id,
                    "participants": participant_ids,
                    "request_number": request_number,
                },
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
                (utcnow(), meeting_id),
            )
            if cur.rowcount:
                self._conn.execute(
                    "DELETE FROM chat_reminder_log WHERE meeting_id = ?",
                    (meeting_id,),
                )
                self._record_audit(
                    action="meeting_canceled",
                    entity_type="meeting",
                    entity_id=meeting_id,
                    payload={},
                )
                return True
        return False

    def reschedule_meeting(self, meeting_id: str, scheduled_at: datetime) -> bool:
        normalized_dt = ensure_timezone(scheduled_at, self._timezone)
        normalized_dt = normalized_dt.astimezone(
            self._timezone or normalized_dt.tzinfo or timezone.utc
        )
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
                (scheduled_iso, date_utc, time_utc, utcnow(), meeting_id),
            )
            if cur.rowcount:
                self._conn.execute(
                    "DELETE FROM chat_reminder_log WHERE meeting_id = ?",
                    (meeting_id,),
                )
                self._record_audit(
                    action="meeting_updated",
                    entity_type="meeting",
                    entity_id=meeting_id,
                    payload={"scheduled_at": scheduled_iso},
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
        payload: Dict[str, Any] = {}
        if title is not None:
            fields.append("title = ?")
            params.append(title)
            payload["title"] = title
        if meeting_type is not None:
            fields.append("type = ?")
            params.append(meeting_type)
            payload["type"] = meeting_type
        if room is not None:
            fields.append("room = ?")
            params.append(room)
            payload["room"] = room
        if request_number is not None:
            fields.append("ticket_no = ?")
            params.append(request_number)
            payload["request_number"] = request_number
        if scheduled_at is not None:
            normalized_dt = ensure_timezone(scheduled_at, self._timezone)
            normalized_dt = normalized_dt.astimezone(
                self._timezone or normalized_dt.tzinfo or timezone.utc
            )
            utc_dt = normalized_dt.astimezone(timezone.utc)
            fields.append("scheduled_at = ?")
            params.append(normalized_dt.isoformat(timespec="seconds"))
            fields.append("date_utc = ?")
            params.append(utc_dt.date().isoformat())
            fields.append("start_time_utc = ?")
            params.append(utc_dt.time().isoformat(timespec="seconds"))
            fields.append("reminder_sent = 0")
            fields.append("status = 'moved'")
            payload["scheduled_at"] = normalized_dt.isoformat(timespec="seconds")
        if not fields:
            return self.get_meeting(meeting_id)
        fields.append("updated_at = ?")
        params.append(utcnow())
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
            self._record_audit(
                action="meeting_updated",
                entity_type="meeting",
                entity_id=meeting_id,
                payload=payload,
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
                    (utcnow(), meeting_id),
                )
            self._record_audit(
                action="reminder_sent",
                entity_type="meeting",
                entity_id=meeting_id,
                payload={"chat_id": int(chat_id), "lead_time": int(lead_time)},
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
        return cast(RoleName, row[0]) if row[0] in ("admin", "user") else None

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
        normalized_leads = normalize_lead_times(
            lead_times or self._default_lead_times or (1800, 600, 0)
        )
        admins: list[int] = []
        for candidate in admin_ids or []:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value not in admins:
                admins.append(value)
        now = utcnow()
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
            self._record_audit(
                action="chat_updated",
                entity_type="chat",
                entity_id=str(chat_id),
                payload={
                    "title": title,
                    "lead_times": normalized_leads,
                    "admins": admins,
                    "timezone": timezone,
                },
            )
        chat = self.get_chat(chat_id)
        if chat is None:
            raise RuntimeError("Failed to register chat")
        return chat

    def set_chat_lead_times(self, chat_id: int, lead_times: Sequence[int]) -> Optional[ChatSettings]:
        normalized = normalize_lead_times(lead_times)
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
                (utcnow(), int(chat_id)),
            )
            self._record_audit(
                action="chat_updated",
                entity_type="chat",
                entity_id=str(chat_id),
                payload={"lead_times": normalized},
            )
        return self.get_chat(chat_id)

    def add_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        return self.set_chat_role(chat_id, user_id, "admin")

    def remove_chat_admin(self, chat_id: int, user_id: int) -> Optional[ChatSettings]:
        return self.set_chat_role(chat_id, user_id, "user")

    def set_chat_role(self, chat_id: int, user_id: int, role: str) -> Optional[ChatSettings]:
        normalized_role = normalize_role(role)
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
                (utcnow(), int(chat_id)),
            )
            self._record_audit(
                action="chat_updated",
                entity_type="chat",
                entity_id=str(chat_id),
                payload={"user_id": int(user_id), "role": normalized_role},
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
                (utcnow(), int(chat_id)),
            )
            self._record_audit(
                action="chat_updated",
                entity_type="chat",
                entity_id=str(chat_id),
                payload={"user_id": int(user_id), "role": None},
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
            self._record_audit(
                action="settings_updated",
                entity_type="setting",
                entity_id=name,
                payload={"value": value},
            )

    def get_user_settings(self, user_id: int) -> UserSettings:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        if not row:
            settings = UserSettings(id=int(user_id))
            return ensure_user_defaults(
                settings,
                default_lead_time=self._default_user_lead_time,
                default_locale=self._default_locale,
                default_timezone=self._default_timezone_name,
            )
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
        return ensure_user_defaults(
            settings,
            default_lead_time=self._default_user_lead_time,
            default_locale=self._default_locale,
            default_timezone=self._default_timezone_name,
        )

    def save_user_settings(self, settings: UserSettings) -> UserSettings:
        normalized = ensure_user_defaults(
            settings,
            default_lead_time=self._default_user_lead_time,
            default_locale=self._default_locale,
            default_timezone=self._default_timezone_name,
        )
        now = utcnow()
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
            self._record_audit(
                action="settings_updated",
                entity_type="user",
                entity_id=str(normalized.id),
                user_id=int(normalized.id),
                payload=normalized.to_dict(),
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
        scheduled = ensure_timezone(scheduled, self._timezone)
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
            normalized_role = normalize_role(role)
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
        return ensure_chat_defaults(
            ChatSettings.from_dict(payload),
            default_lead_times=self._default_lead_times,
            default_timezone=self._default_timezone_name,
        )

