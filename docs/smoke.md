# Smoke Checklist

1. Start the bot via `python -m telegram_meeting_bot` and ensure it launches without errors.
2. In a private chat, send `30.10 МТС 10:00 7А 102455` and confirm the bot acknowledges the meeting.
3. Configure lead time and timezone through `/settings` and verify the values persist.
4. Trigger a reminder by creating a meeting with lead time in the past and observe delivery in the registered chat or DM.
5. Click inline buttons for snooze and cancel to ensure they respond only once and update the UI.
6. Run `/export` and confirm an `.ics` file is provided.
7. Execute `/status` as an admin to view metrics snapshot.
8. Review `logs/app` and `logs/audit` for daily rotation files after activity.
