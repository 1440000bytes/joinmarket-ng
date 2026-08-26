"""Source mixdepth candidate ordering for maker CoinJoins."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class MixdepthSelectionPolicy(StrEnum):
    """Policies for choosing a source mixdepth among eligible balances."""

    BALANCED = "balanced"
    CONCENTRATED = "concentrated"


def mixdepth_attempt_order(
    eligible_mixdepths: Mapping[int, int],
    mixdepth_count: int,
    policy: MixdepthSelectionPolicy,
) -> list[int]:
    """Return eligible source mixdepths in the order they should be attempted.

    ``concentrated`` follows the legacy yg-privacyenhanced cyclic-gap selector.
    After each choice, it removes that depth and recomputes the next gap so
    reservation conflicts retain the same policy semantics.
    """
    _validate_inputs(eligible_mixdepths, mixdepth_count, policy)

    if policy is MixdepthSelectionPolicy.BALANCED:
        return sorted(
            eligible_mixdepths,
            key=lambda mixdepth: (-eligible_mixdepths[mixdepth], mixdepth),
        )

    remaining = set(eligible_mixdepths)
    candidates: list[int] = []
    while remaining:
        candidate = _select_largest_cyclic_gap_end(remaining, mixdepth_count)
        candidates.append(candidate)
        remaining.remove(candidate)
    return candidates


def _select_largest_cyclic_gap_end(available: set[int], mixdepth_count: int) -> int:
    """Select the legacy largest-gap endpoint, preserving its first-tie rule."""
    ordered = sorted(available)
    intervals = [mixdepth_count + ordered[0] - ordered[-1]]
    intervals.extend(ordered[index + 1] - ordered[index] for index in range(len(ordered) - 1))
    return ordered[max(range(len(ordered)), key=intervals.__getitem__)]


def _validate_inputs(
    eligible_mixdepths: Mapping[int, int],
    mixdepth_count: int,
    policy: MixdepthSelectionPolicy,
) -> None:
    if (
        isinstance(mixdepth_count, bool)
        or not isinstance(mixdepth_count, int)
        or mixdepth_count < 1
    ):
        raise ValueError(f"mixdepth_count must be a positive integer, got {mixdepth_count!r}")
    if not isinstance(policy, MixdepthSelectionPolicy):
        raise ValueError(f"unknown mixdepth selection policy: {policy!r}")

    for mixdepth, balance in eligible_mixdepths.items():
        if isinstance(mixdepth, bool) or not isinstance(mixdepth, int):
            raise ValueError(f"mixdepth must be an integer, got {mixdepth!r}")
        if not 0 <= mixdepth < mixdepth_count:
            raise ValueError(
                f"eligible mixdepth {mixdepth} is outside 0..{mixdepth_count - 1}"
            )
        if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
            raise ValueError(f"balance for mixdepth {mixdepth} must be a non-negative integer")
