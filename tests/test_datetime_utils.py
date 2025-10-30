from datetime import datetime, time, timedelta, timezone

from telegram_meeting_bot.utils import datetime as dt_utils


def test_next_occurrence_daily_and_weekly():
    start = datetime(2024, 10, 1, 12, tzinfo=timezone.utc)
    assert dt_utils.next_occurrence(start, "daily") == start + timedelta(days=1)
    assert dt_utils.next_occurrence(start, "weekly") == start + timedelta(weeks=1)
    assert dt_utils.next_occurrence(start, "none") is None


def test_combine_date_time_returns_utc():
    date_value = datetime(2024, 10, 1, tzinfo=timezone.utc)
    combined = dt_utils.combine_date_time(date_value, time(10, 30), "Europe/Moscow")
    assert combined.tzinfo == timezone.utc
    assert combined.hour == 7
