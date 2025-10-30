from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Literal, Optional

try:  # pragma: no cover - compatibility shim across aiogram versions
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
    try:
        from aiogram.exceptions import TelegramRetryAfter as RetryAfter
    except ImportError:
        from aiogram.exceptions import RetryAfter  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - minimal fallback for tests
    class TelegramBadRequest(Exception):
        pass

    class TelegramNetworkError(Exception):
        pass

    class RetryAfter(Exception):  # type: ignore[misc]
        def __init__(self, retry_after: float = 1.0) -> None:
            super().__init__("Retry after fallback")
            self.retry_after = retry_after

from ..config import NetworkConfig
from ..utils.metrics import MetricsCollector

logger = logging.getLogger("telegram_meeting_bot.services.telegram")
audit_logger = logging.getLogger("telegram_meeting_bot.audit")


Profile = Literal["ui", "heavy"]


@dataclass(slots=True)
class TelegramCall:
    op_id: str
    profile: Profile
    func: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...]
    kwargs: Dict[str, Any]
    future: asyncio.Future[Any]


class TelegramSender:
    def __init__(
        self,
        *,
        bot,
        network: NetworkConfig,
        metrics: MetricsCollector,
    ) -> None:
        self._bot = bot
        self._network = network
        self._metrics = metrics
        self._queue: asyncio.Queue[TelegramCall] = asyncio.Queue()
        self._recent_ops: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def safe_tg_call(
        self,
        profile: Profile,
        op_id: str,
        func: Callable[..., Awaitable[Any]],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        call = TelegramCall(op_id=op_id, profile=profile, func=func, args=args, kwargs=kwargs, future=future)
        try:
            self._queue.put_nowait(call)
        except asyncio.QueueFull:  # pragma: no cover - queue is unbounded but guard anyway
            await self._queue.put(call)
        await self._metrics.set(queue_size=self._queue.qsize())
        return await future

    async def worker_tick(self) -> None:
        drained = 0
        while True:
            try:
                call = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            drained += 1
            await self._process_call(call)
        if drained:
            await self._metrics.set(queue_size=self._queue.qsize())

    async def _process_call(self, call: TelegramCall) -> None:
        op_id = call.op_id
        now = time.monotonic()
        async with self._lock:
            # Drop operations that were recently completed to keep idempotency
            stale_before = now - 60
            for key, ts in list(self._recent_ops.items()):
                if ts < stale_before:
                    self._recent_ops.pop(key, None)
            if op_id in self._recent_ops:
                if not call.future.done():
                    call.future.set_result(None)
                audit_logger.info('{"event":"CLICK_DEDUP","op_id":"%s"}', op_id)
                return
            self._recent_ops[op_id] = now

        try:
            started = time.monotonic()
            result = await self._execute_with_retry(call)
        except Exception as exc:  # pragma: no cover - propagated to caller
            if not call.future.done():
                call.future.set_exception(exc)
        else:
            if not call.future.done():
                call.future.set_result(result)
            await self._metrics.record_latency(time.monotonic() - started)

    async def _execute_with_retry(self, call: TelegramCall) -> Any:
        profile = call.profile
        if profile == "ui":
            retries = self._network.ui_retries
            connect_timeout = self._network.ui_connect_timeout
            read_timeout = self._network.ui_read_timeout
            jitter_min = self._network.ui_jitter_min
            jitter_max = self._network.ui_jitter_max
            backoff = 0.0
        else:
            retries = self._network.heavy_max_retries
            connect_timeout = self._network.connect_timeout
            read_timeout = self._network.request_timeout
            jitter_min = 0.0
            jitter_max = 0.0
            backoff = self._network.heavy_backoff_start

        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                timeout = read_timeout
                kwargs = dict(call.kwargs)
                request_timeout = max(connect_timeout, timeout)
                kwargs.setdefault("request_timeout", request_timeout)
                kwargs.setdefault("timeout", request_timeout)
                result = await call.func(*call.args, **kwargs)
                await self._metrics.incr(sends=1)
                return result
            except RetryAfter as exc:  # type: ignore[attr-defined]
                wait_for = float(getattr(exc, "retry_after", 1))
                audit_logger.info(
                    '{"event":"NETWORK_RETRY","op_id":"%s","delay":%.3f}',
                    call.op_id,
                    wait_for,
                )
                await asyncio.sleep(wait_for)
                last_exc = exc
                await self._metrics.record_retry()
            except TelegramBadRequest as exc:
                if "Message is not modified" in str(exc):
                    logger.info("message not modified op_id=%s", call.op_id)
                    return None
                last_exc = exc
                break
            except (TelegramNetworkError, asyncio.TimeoutError) as exc:
                last_exc = exc
                delay = self._compute_delay(profile, attempt, backoff, jitter_min, jitter_max)
                audit_logger.info(
                    '{"event":"NETWORK_RETRY","op_id":"%s","delay":%.3f}',
                    call.op_id,
                    delay,
                )
                await self._metrics.record_retry()
                await asyncio.sleep(delay)
            except Exception as exc:  # pragma: no cover - unexpected error
                last_exc = exc
                break
        if last_exc:
            if isinstance(last_exc, asyncio.TimeoutError):
                await self._metrics.record_timeout()
            logger.warning("telegram call failed op_id=%s error=%s", call.op_id, last_exc)
            raise last_exc
        return None

    def _compute_delay(
        self,
        profile: Profile,
        attempt: int,
        backoff: float,
        jitter_min: float,
        jitter_max: float,
    ) -> float:
        if profile == "ui":
            base = random.uniform(jitter_min, jitter_max) if jitter_max else 0.2
            return base
        delay = backoff * (2 ** attempt)
        return min(delay, self._network.heavy_backoff_cap)

    @property
    def bot(self):
        return self._bot

    def queue_size(self) -> int:
        return self._queue.qsize()
