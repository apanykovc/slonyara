# Slonyara

Utilities for structured logging across the project.

## Logging

Use the helpers in `slonyara.logging_config` to configure logging once at
application start:

```python
from slonyara.logging_config import setup_logging, get_category_logger

setup_logging(log_file="logs/app.log")
logger = get_category_logger("meeting_created")
logger.info("Scheduled a new meeting", extra={"meeting_id": 42})
```

Console output is colourised by category, while the file handler stores
JSON lines that can be ingested by log processors. Supported categories
are `meeting_created`, `reminder_sent`, and `error`.
