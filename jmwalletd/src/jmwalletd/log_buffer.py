"""In-memory ring buffer sink for jmwalletd logs.

jam's Logs page expects to fetch the daemon's recent log output as plain text.
The reference joinmarket-clientserver writes a ``jmwalletd_stdout.log`` file on
disk, but jm-ng currently logs only to stderr. Instead of forcing a file
dependency, we attach a loguru sink that keeps the most recent N formatted log
lines in a thread-safe deque; a small router serves that snapshot back to jam.

The buffer is bounded so long-running daemons cannot grow the heap
unboundedly, and a secondary soft cap on total bytes prevents pathological
spam from blowing past reasonable memory even within the line limit.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from collections import deque

from loguru import logger

__all__ = ["LogRingBuffer", "get_log_buffer", "install_log_sink"]


class LogRingBuffer:
    """Thread-safe bounded in-memory log buffer.

    Stores formatted log lines (one per loguru record) up to ``max_lines``
    entries or ``max_bytes`` total bytes, whichever fills first.
    """

    def __init__(self, max_lines: int = 2000, max_bytes: int = 1_000_000) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._size_bytes = 0
        self._lock = threading.Lock()

    def append(self, message: str) -> None:
        """Append a formatted log line. ``message`` already ends in ``\\n``."""
        with self._lock:
            # Enforce the byte cap before adding by dropping oldest entries.
            while self._lines and self._size_bytes + len(message) > self._max_bytes:
                oldest = self._lines.popleft()
                self._size_bytes -= len(oldest)

            if len(self._lines) == self._max_lines:
                # deque will drop the oldest on append; update accounting first.
                self._size_bytes -= len(self._lines[0])

            self._lines.append(message)
            self._size_bytes += len(message)

    def text(self) -> str:
        """Return a snapshot of the buffer joined as plain text."""
        with self._lock:
            return "".join(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._size_bytes = 0


_buffer: LogRingBuffer | None = None
_sink_id: int | None = None
_stderr_sink_id: int | None = 0


def get_log_buffer() -> LogRingBuffer:
    """Return the process-wide log ring buffer, creating it on first use."""
    global _buffer
    if _buffer is None:
        _buffer = LogRingBuffer()
    return _buffer


def install_log_sink(level: str = "DEBUG") -> None:
    """Attach the ring buffer as a loguru sink and reconfigure stderr logging.

    Safe to call multiple times; existing sinks are removed first so the
    level can be updated at runtime without duplicating records.
    """
    global _sink_id, _stderr_sink_id
    level_str = level.upper()

    if _stderr_sink_id is not None:
        with contextlib.suppress(ValueError):
            logger.remove(_stderr_sink_id)
        _stderr_sink_id = None
    _stderr_sink_id = logger.add(sys.stderr, level=level_str)

    buffer = get_log_buffer()
    if _sink_id is not None:
        with contextlib.suppress(ValueError):
            # Already removed elsewhere (e.g. logger.remove()).
            logger.remove(_sink_id)
        _sink_id = None

    _sink_id = logger.add(
        buffer.append,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        ),
        level=level_str,
        colorize=False,
        enqueue=False,
    )
