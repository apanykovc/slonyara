"""Queued Telegram sender with retry and middleware helpers."""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypeVar

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods.base import TelegramMethod
from aiogram.types import TelegramObject
from aiogram import BaseMiddleware

try:  # pragma: no cover - optional dependency
    import httpx
except Exception:  # pragma: no cover - package not installed in tests
    httpx = None  # type: ignore[assignment]


_logger = logging.getLogger(__name__)

T = TypeVar("T")

_CURRENT_QUEUE: ContextVar[str] = ContextVar("telegram_sender_queue", default="background")


@dataclass(slots=True)
class TelegramSenderConfig:
    """Configuration profile for a sender queue."""

    timeout: float = 5.0
    max_attempts: int = 3
    rps: float = 15.0
    retry_base_delay: float = 0.5
    retry_multiplier: float = 2.0
    retry_max_delay: float = 5.0


@dataclass(slots=True)
class _SendJob:
    factory: Callable[[], Awaitable[T]]
    future: asyncio.Future[T]
    timeout: float
    max_attempts: int
    attempts: int = 0
    base_delay: float = 0.5
    multiplier: float = 2.0
    max_delay: float = 5.0
    label: str = ""


class TelegramSender:
    """Serialize Telegram API calls through prioritised queues."""

    def __init__(
        self,
        *,
        ui: TelegramSenderConfig,
        background: TelegramSenderConfig,
        rate_limit_buffer: float = 0.05,
    ) -> None:
        self._ui_config = ui
        self._background_config = background
        self._rate_limit_buffer = max(0.0, rate_limit_buffer)
        self._ui_queue: asyncio.Queue[_SendJob[Any]] = asyncio.Queue()
        self._bg_queue: asyncio.Queue[_SendJob[Any]] = asyncio.Queue()
        self._ui_worker: Optional[asyncio.Task[None]] = None
        self._bg_worker: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Start background workers."""

        if self._ui_worker is None:
            self._ui_worker = asyncio.create_task(
                self._run_worker(self._ui_queue, self._ui_config, name="ui"),
                name="telegram-sender-ui",
            )
        if self._bg_worker is None:
            self._bg_worker = asyncio.create_task(
                self._run_worker(self._bg_queue, self._background_config, name="background"),
                name="telegram-sender-bg",
            )

    async def stop(self) -> None:
        """Stop workers and cancel pending jobs."""

        for queue in (self._ui_queue, self._bg_queue):
            while not queue.empty():
                job = queue.get_nowait()
                if not job.future.done():
                    job.future.cancel()
                queue.task_done()
        for task in (self._ui_worker, self._bg_worker):
            if task is not None:
                task.cancel()
        for task in (self._ui_worker, self._bg_worker):
            if task is None:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._ui_worker = None
        self._bg_worker = None

    async def request(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
        max_attempts: int | None = None,
        label: str = "",
        queue: str | None = None,
    ) -> T:
        """Schedule a request using the current queue context."""

        target = queue or _CURRENT_QUEUE.get()
        if target == "ui":
            return await self._submit(
                self._ui_queue,
                self._ui_config,
                factory,
                timeout=timeout,
                max_attempts=max_attempts,
                label=label,
            )
        return await self._submit(
            self._bg_queue,
            self._background_config,
            factory,
            timeout=timeout,
            max_attempts=max_attempts,
            label=label,
        )

    async def send_ui(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
        max_attempts: int | None = None,
        label: str = "",
    ) -> T:
        """Schedule a UI response for delivery."""

        return await self.request(
            factory,
            timeout=timeout,
            max_attempts=max_attempts,
            label=label,
            queue="ui",
        )

    async def send_background(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
        max_attempts: int | None = None,
        label: str = "",
    ) -> T:
        """Schedule a background request for delivery."""

        return await self.request(
            factory,
            timeout=timeout,
            max_attempts=max_attempts,
            label=label,
            queue="background",
        )

    def use_queue(self, name: str) -> Token[str]:
        """Switch queue context and return reset token."""

        return _CURRENT_QUEUE.set(name)

    def reset_queue(self, token: Token[str]) -> None:
        """Reset queue context to previous value."""

        _CURRENT_QUEUE.reset(token)

    @contextmanager
    def queue_context(self, name: str):
        token = self.use_queue(name)
        try:
            yield
        finally:
            self.reset_queue(token)

    async def _submit(
        self,
        queue: asyncio.Queue[_SendJob[Any]],
        config: TelegramSenderConfig,
        factory: Callable[[], Awaitable[T]],
        *,
        timeout: float | None,
        max_attempts: int | None,
        label: str,
    ) -> T:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        job = _SendJob(
            factory=factory,
            future=future,
            timeout=config.timeout if not timeout or timeout <= 0 else timeout,
            max_attempts=config.max_attempts if not max_attempts or max_attempts <= 0 else max_attempts,
            base_delay=config.retry_base_delay,
            multiplier=config.retry_multiplier,
            max_delay=config.retry_max_delay,
            label=label,
        )
        queue.put_nowait(job)
        return await future

    async def _run_worker(
        self,
        queue: asyncio.Queue[_SendJob[Any]],
        config: TelegramSenderConfig,
        *,
        name: str,
    ) -> None:
        min_interval = 1.0 / config.rps if config.rps > 0 else 0.0
        last_sent = 0.0
        loop = asyncio.get_running_loop()
        http_errors: tuple[type[BaseException], ...] = (aiohttp.ClientError,)
        if httpx is not None:  # pragma: no cover - optional dependency
            http_errors = http_errors + (httpx.HTTPError,)  # type: ignore[operator]

        try:
            while True:
                job = await queue.get()
                wait_time = min_interval - (loop.time() - last_sent)
                if wait_time > 0:
                    await asyncio.sleep(wait_time + self._rate_limit_buffer)
                try:
                    result = await asyncio.wait_for(job.factory(), timeout=job.timeout)
                except asyncio.TimeoutError as exc:
                    await self._handle_retry(queue, job, name, "timeout", exc)
                except TelegramRetryAfter as exc:
                    await self._handle_retry(
                        queue,
                        job,
                        name,
                        "429",
                        exc,
                        delay=exc.retry_after,
                        hard_limit=True,
                    )
                except TelegramBadRequest as exc:
                    self._fail_job(job, exc)
                except TelegramServerError as exc:
                    await self._handle_retry(queue, job, name, "5xx", exc)
                except TelegramNetworkError as exc:
                    await self._handle_retry(queue, job, name, "network", exc)
                except http_errors as exc:  # type: ignore[arg-type]
                    await self._handle_retry(queue, job, name, "http", exc)
                except Exception as exc:  # pragma: no cover - unexpected errors
                    self._fail_job(job, exc)
                else:
                    if not job.future.done():
                        job.future.set_result(result)
                    last_sent = loop.time()
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            _logger.debug("Telegram sender worker %s cancelled", name)
            raise

    async def _handle_retry(
        self,
        queue: asyncio.Queue[_SendJob[Any]],
        job: _SendJob[Any],
        name: str,
        reason: str,
        exc: BaseException,
        *,
        delay: float | None = None,
        hard_limit: bool = False,
    ) -> None:
        job.attempts += 1
        if job.attempts >= job.max_attempts or (hard_limit and delay is None):
            _logger.warning(
                "Telegram %s request %s failed after %s attempts (%s)",
                name,
                job.label or "<unnamed>",
                job.attempts,
                reason,
            )
            self._fail_job(job, exc)
            return
        if delay is None:
            delay = min(job.max_delay, job.base_delay * (job.multiplier ** (job.attempts - 1)))
        _logger.warning(
            "Retrying Telegram %s request %s in %.2fs (%s attempt %s/%s)",
            name,
            job.label or "<unnamed>",
            delay,
            reason,
            job.attempts,
            job.max_attempts,
        )
        await asyncio.sleep(delay)
        queue.put_nowait(job)

    @staticmethod
    def _fail_job(job: _SendJob[Any], exc: BaseException) -> None:
        if not job.future.done():
            job.future.set_exception(exc)

    async def __aenter__(self) -> "TelegramSender":  # pragma: no cover - convenience
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:  # pragma: no cover - convenience
        await self.stop()


class SenderAiohttpSession(AiohttpSession):
    """Aiohttp session that proxies requests through :class:`TelegramSender`."""

    def __init__(self, sender: TelegramSender, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sender = sender

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[T],
        timeout: Optional[int] = None,
    ) -> T:
        label = getattr(method, "__api_method__", "<unknown>")
        parent_make_request = super().make_request  # захватываем bound-метод с self

        return await self._sender.request(
            lambda: parent_make_request(bot, method, timeout=timeout),
            timeout=float(timeout) if timeout is not None else None,
            label=label,
        )
    
class SenderContextMiddleware(BaseMiddleware):
    """Middleware that routes handler requests to the UI queue."""

    def __init__(self, sender: TelegramSender) -> None:
        super().__init__()
        self._sender = sender

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        token = self._sender.use_queue("ui")
        try:
            return await handler(event, data)
        finally:
            self._sender.reset_queue(token)
