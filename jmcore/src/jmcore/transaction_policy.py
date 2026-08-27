"""Shared Bitcoin transaction fingerprint policy."""

from __future__ import annotations

from typing import Protocol

from jmcore.randomness import secure_random

MAX_LOCKTIME = 0xFFFFFFFF
RBF_SEQUENCE = 0xFFFFFFFD
NON_RBF_LOCKTIME_SEQUENCE = 0xFFFFFFFE


class RandomSource(Protocol):
    """Randomness interface needed by anti-fee-sniping locktime selection."""

    def randint(self, start: int, end: int) -> int: ...


def compute_tx_locktime(current_height: int, rng: RandomSource = secure_random) -> int:
    """Return a reference-compatible anti-fee-sniping locktime."""
    if (
        not isinstance(current_height, int)
        or isinstance(current_height, bool)
        or not 0 <= current_height <= MAX_LOCKTIME
    ):
        raise ValueError(f"Invalid current block height: {current_height!r}")
    if current_height == 0:
        return 0
    if rng.randint(0, 9) == 0:
        return max(1, current_height - rng.randint(0, 99))
    return current_height
