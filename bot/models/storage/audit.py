"""Audit log helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _default_serializer(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@dataclass(slots=True)
class AuditEvent:
    """Structured representation of an audit log entry."""

    action: str
    entity_type: str
    entity_id: str | None = None
    payload: Mapping[str, Any] | None = None
    user_id: int | None = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_db_tuple(self) -> tuple[str, int | None, str, str, str | None]:
        payload_json: str | None = None
        if self.payload is not None:
            payload_json = json.dumps(self.payload, ensure_ascii=False, default=_default_serializer)
        return (
            self.at.isoformat(timespec="seconds"),
            self.user_id,
            self.action,
            self.entity_type,
            self.entity_id,
            payload_json,
        )


__all__ = ["AuditEvent"]
