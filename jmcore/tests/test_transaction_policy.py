"""Tests for shared Bitcoin transaction fingerprint policy."""

from __future__ import annotations

from typing import Any

import pytest

from jmcore.transaction_policy import compute_tx_locktime


class MockRandom:
    def __init__(self, values: list[int]):
        self._values = iter(values)

    def randint(self, start: int, end: int) -> int:
        value = next(self._values)
        assert start <= value <= end
        return value


def test_uses_current_height_normally() -> None:
    assert compute_tx_locktime(840_000, MockRandom([1])) == 840_000


def test_randomly_backdates_within_reference_window() -> None:
    assert compute_tx_locktime(840_000, MockRandom([0, 37])) == 839_963


def test_backdating_is_bounded_at_one() -> None:
    assert compute_tx_locktime(42, MockRandom([0, 99])) == 1


def test_genesis_height_remains_final() -> None:
    assert compute_tx_locktime(0, MockRandom([])) == 0


@pytest.mark.parametrize("height", [-1, True, 0x1_0000_0000, 1.5])
def test_rejects_invalid_height(height: Any) -> None:
    with pytest.raises(ValueError, match="Invalid current block height"):
        compute_tx_locktime(height)
