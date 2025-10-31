from datetime import datetime, timezone

import pytest

from telegram_meeting_bot.utils import parsing


@pytest.fixture(autouse=True)
def freeze_now(monkeypatch):
    current = datetime(2024, 10, 1, tzinfo=timezone.utc)

    def fake_now():
        return current

    monkeypatch.setattr(parsing, "now_utc", fake_now)


def test_parse_strict_format():
    parsed = parsing.parse_event("30.10 МТС 10:00 7А 102455", "Europe/Moscow")
    assert parsed is not None
    assert parsed.tag == "МТС"
    assert parsed.room == "7А"
    assert parsed.ticket == "102455"
    local = parsed.starts_at.astimezone(timezone.utc)
    assert local.day == 30
    assert local.hour == 7  # 10:00 Moscow -> 07:00 UTC in October


def test_parse_natural_format():
    parsed = parsing.parse_event("завтра 09:30 Демо 9Б 778899", "Europe/Moscow")
    assert parsed is not None
    assert parsed.tag == "Демо"
    assert parsed.room == "9Б"
    assert parsed.ticket == "778899"
    assert parsed.starts_at > datetime(2024, 10, 1, tzinfo=timezone.utc)
