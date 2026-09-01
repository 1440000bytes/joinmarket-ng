"""Isolated Apprise delivery worker for notifications.

Apprise HTTP plugins use process-global proxy environment variables. Keep that
state in a dedicated child process so notifications cannot affect the parent
JoinMarket process or any of its concurrent tasks.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import multiprocessing as mp
import os
import queue
import re
import time
import weakref
from collections.abc import Callable, MutableMapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from jmcore.tor_isolation import IsolationCategory, build_isolated_proxy_url

PROXY_ENVIRONMENT_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)

_WORKER_START_TIMEOUT = 10.0
_WORKER_SEND_TIMEOUT = 65.0
_WORKER_JOIN_TIMEOUT = 1.0
_HTTP_STATUS_RE = re.compile(r"\b([45]\d{2})\b")
_SAFE_HTTP_DIAGNOSTIC_RE = re.compile(r"Notification service returned HTTP status [45]\d{2}")

_APPRISE_UNAVAILABLE_DIAGNOSTIC = "Apprise is not installed"
_INITIALIZATION_TIMEOUT_DIAGNOSTIC = "Notification worker initialization timed out"
_WORKER_STOPPED_DIAGNOSTIC = "Notification worker stopped unexpectedly"
_GENERIC_INITIALIZATION_DIAGNOSTIC = "Apprise initialization failed"
_GENERIC_DELIVERY_DIAGNOSTIC = "Apprise notification delivery failed"
_SAFE_DIAGNOSTICS = frozenset(
    {
        _APPRISE_UNAVAILABLE_DIAGNOSTIC,
        _INITIALIZATION_TIMEOUT_DIAGNOSTIC,
        _WORKER_STOPPED_DIAGNOSTIC,
        _GENERIC_INITIALIZATION_DIAGNOSTIC,
        _GENERIC_DELIVERY_DIAGNOSTIC,
        "TLS certificate verification failed",
        "TLS connection failed",
        "Notification proxy connection failed",
        "Notification connection was refused",
        "Notification connection timed out",
        "Notification host resolution failed",
        "Notification service authentication failed",
        "Notification service authorization failed",
        "No valid notification services configured",
    }
)


@dataclass(frozen=True)
class NotificationWorkerConfig:
    """Configuration transferred to the isolated notification worker."""

    urls: tuple[str, ...]
    use_tor: bool
    tor_socks_host: str
    tor_socks_port: int
    stream_isolation: bool


@dataclass(frozen=True)
class NotificationWorkerResult:
    """A bounded delivery result that contains no notification content."""

    success: bool
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostic", _sanitize_worker_diagnostic(self.diagnostic))


class NotificationWorker(Protocol):
    """Synchronous interface used by :class:`jmcore.notifications.Notifier`."""

    @property
    def closed(self) -> bool:
        """Whether the worker can no longer accept requests."""
        ...

    def start(self) -> NotificationWorkerResult:
        """Start the worker and initialize its Apprise services."""
        ...

    def send(self, title: str, body: str, priority: str) -> NotificationWorkerResult:
        """Deliver one notification."""
        ...

    def close(self) -> None:
        """Stop the worker and release its resources."""
        ...


def _configure_worker_environment(
    config: NotificationWorkerConfig,
    environment: MutableMapping[str, str] | None = None,
    isolated_proxy_builder: Callable[[str, int, IsolationCategory], str] = build_isolated_proxy_url,
) -> None:
    """Apply the worker's complete proxy policy to its private environment."""
    target_environment = os.environ if environment is None else environment
    for key in PROXY_ENVIRONMENT_KEYS:
        target_environment.pop(key, None)

    if not config.use_tor:
        return

    if config.stream_isolation:
        proxy_url = isolated_proxy_builder(
            config.tor_socks_host,
            config.tor_socks_port,
            IsolationCategory.NOTIFICATION,
        )
    else:
        proxy_url = f"socks5h://{config.tor_socks_host}:{config.tor_socks_port}"

    # requests consults lower-case names first. Set both forms after removing
    # inherited values so every Apprise HTTP plugin gets the same proxy.
    target_environment["HTTP_PROXY"] = proxy_url
    target_environment["HTTPS_PROXY"] = proxy_url
    target_environment["http_proxy"] = proxy_url
    target_environment["https_proxy"] = proxy_url


def _sanitize_worker_diagnostic(
    detail: str | None,
    fallback: str | None = _GENERIC_DELIVERY_DIAGNOSTIC,
) -> str | None:
    """Map untrusted Apprise text to a bounded, non-sensitive diagnostic."""
    if not detail:
        return None
    if detail in _SAFE_DIAGNOSTICS or _SAFE_HTTP_DIAGNOSTIC_RE.fullmatch(detail):
        return detail

    normalized = detail.lower()
    if "certificate verify" in normalized or "certificate verification" in normalized:
        return "TLS certificate verification failed"
    if "proxy" in normalized or "socks" in normalized:
        return "Notification proxy connection failed"
    if "connection refused" in normalized:
        return "Notification connection was refused"
    if "timed out" in normalized or "timeout" in normalized:
        return "Notification connection timed out"
    if "name or service not known" in normalized or "getaddrinfo" in normalized:
        return "Notification host resolution failed"
    if "unauthorized" in normalized or "authentication" in normalized or "401" in normalized:
        return "Notification service authentication failed"
    if "forbidden" in normalized or "authorization" in normalized or "403" in normalized:
        return "Notification service authorization failed"
    if "ssl" in normalized or "tls" in normalized:
        return "TLS connection failed"
    if status_match := _HTTP_STATUS_RE.search(normalized):
        return f"Notification service returned HTTP status {status_match.group(1)}"
    return fallback


class _AppriseDiagnosticHandler(logging.Handler):
    """Capture only sanitized Apprise diagnostics inside the child process."""

    def __init__(self) -> None:
        super().__init__()
        self.diagnostic: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        diagnostic = _sanitize_worker_diagnostic(record.getMessage(), fallback=None)
        if diagnostic is not None:
            self.diagnostic = diagnostic


def _capture_apprise_diagnostics() -> _AppriseDiagnosticHandler:
    """Keep child transport details out of logs while retaining a safe summary."""
    handler = _AppriseDiagnosticHandler()
    apprise_logger = logging.getLogger("apprise")
    apprise_logger.handlers.clear()
    apprise_logger.addHandler(handler)
    apprise_logger.setLevel(logging.DEBUG)
    apprise_logger.propagate = False
    return handler


def _send_with_apprise(apprise_instance: Any, title: str, body: str, priority: str) -> bool:
    """Deliver with Apprise's async API where available, otherwise synchronously."""
    import apprise

    notify_type = {
        "info": apprise.NotifyType.INFO,
        "success": apprise.NotifyType.SUCCESS,
        "warning": apprise.NotifyType.WARNING,
        "failure": apprise.NotifyType.FAILURE,
    }.get(priority, apprise.NotifyType.INFO)

    async_notify = getattr(apprise_instance, "async_notify", None)
    if callable(async_notify):
        return bool(asyncio.run(async_notify(title=title, body=body, notify_type=notify_type)))
    return bool(apprise_instance.notify(title=title, body=body, notify_type=notify_type))


def _notification_worker_main(
    config: NotificationWorkerConfig,
    request_queue: Any,
    response_queue: Any,
) -> None:
    """Run Apprise in a process whose proxy environment is private."""
    try:
        _configure_worker_environment(config)
        diagnostic_handler = _capture_apprise_diagnostics()

        import apprise

        apprise_instance = apprise.Apprise()
        for url in config.urls:
            apprise_instance.add(url)
        if len(apprise_instance) == 0:
            response_queue.put(
                NotificationWorkerResult(False, "No valid notification services configured")
            )
            return
    except ModuleNotFoundError as error:
        diagnostic = (
            _APPRISE_UNAVAILABLE_DIAGNOSTIC
            if error.name == "apprise"
            else _GENERIC_INITIALIZATION_DIAGNOSTIC
        )
        response_queue.put(NotificationWorkerResult(False, diagnostic))
        return
    except Exception as error:
        response_queue.put(
            NotificationWorkerResult(
                False,
                _sanitize_worker_diagnostic(str(error), _GENERIC_INITIALIZATION_DIAGNOSTIC),
            )
        )
        return

    response_queue.put(NotificationWorkerResult(True))
    while True:
        try:
            request = request_queue.get()
        except (EOFError, OSError):
            return

        operation = request[0]
        if operation == "close":
            return
        if operation != "send":
            response_queue.put(NotificationWorkerResult(False, _GENERIC_DELIVERY_DIAGNOSTIC))
            continue

        _, title, body, priority = request
        try:
            diagnostic_handler.diagnostic = None
            delivered = _send_with_apprise(apprise_instance, title, body, priority)
            response_queue.put(
                NotificationWorkerResult(
                    delivered,
                    None
                    if delivered
                    else diagnostic_handler.diagnostic or _GENERIC_DELIVERY_DIAGNOSTIC,
                )
            )
        except Exception as error:
            response_queue.put(
                NotificationWorkerResult(
                    False,
                    _sanitize_worker_diagnostic(str(error)) or _GENERIC_DELIVERY_DIAGNOSTIC,
                )
            )


_active_workers: weakref.WeakSet[AppriseWorker] = weakref.WeakSet()


def _close_active_workers() -> None:
    for worker in list(_active_workers):
        worker.close()


atexit.register(_close_active_workers)


class AppriseWorker:
    """A single-process, serialized Apprise delivery worker."""

    def __init__(self, config: NotificationWorkerConfig):
        self._config = config
        self._context = mp.get_context("spawn")
        self._request_queue: Any | None = None
        self._response_queue: Any | None = None
        self._process: Any | None = None
        self._closed = False
        _active_workers.add(self)

    @property
    def closed(self) -> bool:
        """Return whether this worker has been shut down."""
        return self._closed

    def start(self) -> NotificationWorkerResult:
        """Spawn the worker and wait for its Apprise initialization result."""
        if self._closed:
            return NotificationWorkerResult(False, _WORKER_STOPPED_DIAGNOSTIC)
        try:
            self._request_queue = self._context.Queue(maxsize=1)
            self._response_queue = self._context.Queue(maxsize=1)
            self._process = self._context.Process(
                target=_notification_worker_main,
                args=(self._config, self._request_queue, self._response_queue),
                name="jm-notification-worker",
                daemon=True,
            )
            self._process.start()
            result = self._receive_response(_WORKER_START_TIMEOUT)
        except Exception:
            self.close()
            return NotificationWorkerResult(False, _GENERIC_INITIALIZATION_DIAGNOSTIC)

        if result is None:
            self.close()
            return NotificationWorkerResult(False, _INITIALIZATION_TIMEOUT_DIAGNOSTIC)
        if not result.success:
            self.close()
        return result

    def send(self, title: str, body: str, priority: str) -> NotificationWorkerResult:
        """Queue one serialized request and return its delivery result."""
        if self._closed or self._request_queue is None:
            return NotificationWorkerResult(False, _WORKER_STOPPED_DIAGNOSTIC)
        try:
            self._request_queue.put(("send", title, body, priority), timeout=1.0)
        except (OSError, queue.Full, ValueError):
            self.close()
            return NotificationWorkerResult(False, _WORKER_STOPPED_DIAGNOSTIC)

        result = self._receive_response(_WORKER_SEND_TIMEOUT)
        if result is None:
            self.close()
            return NotificationWorkerResult(False, _WORKER_STOPPED_DIAGNOSTIC)
        return result

    def close(self) -> None:
        """Stop the child without allowing shutdown to block indefinitely."""
        if self._closed:
            return
        self._closed = True
        process = self._process
        request_queue = self._request_queue

        if process is not None and process.is_alive():
            if request_queue is not None:
                with suppress(OSError, queue.Full, ValueError):
                    request_queue.put_nowait(("close",))
            process.join(_WORKER_JOIN_TIMEOUT)
            if process.is_alive():
                process.terminate()
                process.join(_WORKER_JOIN_TIMEOUT)

        for worker_queue in (self._request_queue, self._response_queue):
            if worker_queue is not None:
                with suppress(OSError, ValueError):
                    worker_queue.close()
        self._process = None
        self._request_queue = None
        self._response_queue = None
        _active_workers.discard(self)

    def _receive_response(self, timeout: float) -> NotificationWorkerResult | None:
        """Wait in short intervals so close or a crashed child is noticed promptly."""
        if self._response_queue is None:
            return None
        deadline = time.monotonic() + timeout
        while True:
            if self._closed:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                response = self._response_queue.get(timeout=min(remaining, 0.1))
                if isinstance(response, NotificationWorkerResult):
                    return response
                return NotificationWorkerResult(False, _WORKER_STOPPED_DIAGNOSTIC)
            except queue.Empty:
                if self._process is None or not self._process.is_alive():
                    return None
            except (EOFError, OSError, ValueError):
                return None
