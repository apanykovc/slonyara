# Manual Testing Checklist

## Basic flows
- Start the bot with `python -m telegram_meeting_bot` and issue the `/start` command in a private chat. Ensure the response arrives immediately.
- In a group chat, register the chat through the admin menu (`/admin → 💬 Регистрация чата`). Verify a confirmation message is shown.
- Create meetings both by sending a one-line message (e.g. `30.10 МТС 10:00 7А 102455`) and through the `/create` wizard. Confirm conflict detection appears when creating overlapping events.
- Trigger reminders by seeding data via `/debug_seed` and waiting until lead time elapses. Confirm reminder messages include the “+15 минут” action and respect quiet hours.
- Test snoozing a reminder via the inline button and confirm the event time shifts forward.
- Reschedule and cancel meetings from the reminder actions (admin only) and ensure conflicts show the resolution buttons.
- Use the `/events` command with pagination and filter parameters (e.g. `type=МТС`, `date=30.10`).
- Call `/agenda`, `/agenda завтра`, and `/agenda неделя` in both private and group contexts to verify the range headers and timezone filtering.
- Export upcoming meetings with `/export` and open the generated `.ics` file in a calendar application to verify formatting.
- Receive the daily digest automatically at 09:00 in both private chats (when direct notifications enabled) and registered group chats.

## Settings and roles
- Open `/settings` in private and group chats, change lead time, timezone, quiet hours, and language. Confirm changes persist.
- Confirm that selecting a destination during event creation remembers the choice, highlights it with a ⭐ marker next time, and that `/settings` can still adjust notification behaviour.
- Toggle chat registration via the settings menu and verify reminders target the correct chat/topic.
- From `/admin`, assign and revoke admin roles using numeric user IDs.
- Run `/status` and verify metrics include queue size, retry/timeout counts, and latency percentiles. Ensure `/status` is blocked for non-admins.
- Execute `/migrate` (when SQLite backend is enabled) and confirm `.json` data is copied to `bot.db` with `.bak` backups created.

## Smoke scenarios
- Create a meeting, allow its reminder to fire, snooze it, reschedule it, then cancel it. Confirm audit logs capture REM_SCHEDULED, REM_FIRED, and REM_CANCELED entries.
- Verify the click guard prevents double submissions by rapidly tapping the same inline button; only one action should occur and the keyboard should freeze.
- Observe app logs every five minutes for the metrics summary line and ensure `Message is not modified` warnings do not trigger retries.
- Confirm `/debug_seed` generates sample events for quick testing.
