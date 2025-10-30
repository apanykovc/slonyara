from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class Metrics:
    sends: int = 0
    retries: int = 0
    timeouts: int = 0
    queue_size: int = 0
    scheduled: int = 0


class MetricsCollector:
    """Collects rolling metrics and latency stats for observability."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._metrics = Metrics()
        self._lock = asyncio.Lock()
        self._logger = logger or logging.getLogger("telegram_meeting_bot.metrics")
        self._latencies: Deque[tuple[float, float]] = deque()
        self._retries: Deque[float] = deque()
        self._timeouts: Deque[float] = deque()

    async def incr(self, **kwargs: int) -> None:
        async with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._metrics, key):
                    setattr(self._metrics, key, getattr(self._metrics, key) + value)

    async def set(self, **kwargs: int) -> None:
        async with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._metrics, key):
                    setattr(self._metrics, key, value)

    async def record_latency(self, latency: float) -> None:
        async with self._lock:
            now = time.time()
            self._latencies.append((now, latency))
            self._trim_older_than(self._latencies, now - 3600)

    async def record_retry(self) -> None:
        async with self._lock:
            now = time.time()
            self._retries.append(now)
            self._trim_older_than(self._retries, now - 3600)
            self._metrics.retries += 1

    async def record_timeout(self) -> None:
        async with self._lock:
            now = time.time()
            self._timeouts.append(now)
            self._trim_older_than(self._timeouts, now - 3600)
            self._metrics.timeouts += 1

    async def snapshot(self) -> Metrics:
        async with self._lock:
            return Metrics(**self._metrics.__dict__)

    async def percentiles(self, window_seconds: int = 3600) -> tuple[float, float]:
        async with self._lock:
            now = time.time()
            values = [lat for ts, lat in self._latencies if ts >= now - window_seconds]
        if not values:
            return 0.0, 0.0
        values.sort()
        p50 = values[len(values) // 2]
        idx95 = int(len(values) * 0.95) - 1
        idx95 = max(0, min(idx95, len(values) - 1))
        return p50, values[idx95]

    async def retry_counts(self, window_seconds: int) -> int:
        async with self._lock:
            now = time.time()
            return sum(1 for ts in self._retries if ts >= now - window_seconds)

    async def timeout_counts(self, window_seconds: int) -> int:
        async with self._lock:
            now = time.time()
            return sum(1 for ts in self._timeouts if ts >= now - window_seconds)

    async def log_summary(self) -> None:
        summary = await self.snapshot()
        p50, p95 = await self.percentiles(300)
        retries_5 = await self.retry_counts(300)
        retries_60 = await self.retry_counts(3600)
        timeouts_5 = await self.timeout_counts(300)
        timeouts_60 = await self.timeout_counts(3600)
        self._logger.info(
            "metrics: queue=%s sends=%s retries=%s/%s timeouts=%s/%s latency_p50=%.3f latency_p95=%.3f",
            summary.queue_size,
            summary.sends,
            retries_5,
            retries_60,
            timeouts_5,
            timeouts_60,
            p50,
            p95,
        )

    def _trim_older_than(self, container: Deque, threshold: float) -> None:
        while container:
            head = container[0]
            ts = head[0] if isinstance(head, tuple) else head
            if ts >= threshold:
                break
            container.popleft()

    async def status_report(self) -> dict[str, float]:
        summary = await self.snapshot()
        p50_5, p95_5 = await self.percentiles(300)
        p50_60, p95_60 = await self.percentiles(3600)
        retries_5 = await self.retry_counts(300)
        retries_60 = await self.retry_counts(3600)
        timeouts_5 = await self.timeout_counts(300)
        timeouts_60 = await self.timeout_counts(3600)
        return {
            "queue_size": summary.queue_size,
            "sends": summary.sends,
            "retries_5m": retries_5,
            "retries_60m": retries_60,
            "timeouts_5m": timeouts_5,
            "timeouts_60m": timeouts_60,
            "latency_p50_5m": p50_5,
            "latency_p95_5m": p95_5,
            "latency_p50_60m": p50_60,
            "latency_p95_60m": p95_60,
        }
