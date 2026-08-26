"""Loguru filters for privacy-sensitive records."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Record

__all__ = ["sensitive_log_filter"]


def sensitive_log_filter(sensitive: bool = False) -> Callable[[Record], bool]:
    """Build a Loguru filter that hides records bound with ``sensitive=True``.

    Privacy-rich log calls must opt in explicitly with
    ``logger.bind(sensitive=True)``. Standard sinks keep those records hidden
    unless sensitive logging is enabled.
    """

    def filter_record(record: Record) -> bool:
        return sensitive or not bool(record["extra"].get("sensitive", False))

    return filter_record
