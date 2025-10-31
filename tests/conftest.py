import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_aiogram_stubs() -> None:
    if "aiogram" in sys.modules:
        return
    aiogram = ModuleType("aiogram")
    exceptions = ModuleType("aiogram.exceptions")

    class TelegramBadRequest(Exception):
        pass

    class TelegramNetworkError(Exception):
        pass

    class RetryAfter(Exception):
        def __init__(self, retry_after: float = 1.0) -> None:
            super().__init__(retry_after)
            self.retry_after = retry_after

    exceptions.TelegramBadRequest = TelegramBadRequest
    exceptions.TelegramNetworkError = TelegramNetworkError
    exceptions.RetryAfter = RetryAfter
    exceptions.TelegramRetryAfter = RetryAfter

    sys.modules["aiogram"] = aiogram
    sys.modules["aiogram.exceptions"] = exceptions


_ensure_aiogram_stubs()
