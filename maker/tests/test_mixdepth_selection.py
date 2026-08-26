"""Tests for maker source mixdepth selection policies."""

from __future__ import annotations

import pytest

from maker.mixdepth_selection import MixdepthSelectionPolicy, mixdepth_attempt_order


def test_balanced_orders_by_descending_balance_with_lower_depth_ties() -> None:
    """The default ordering preserves the existing largest-balance behavior."""
    assert mixdepth_attempt_order(
        {0: 300, 1: 500, 2: 500, 3: 200},
        mixdepth_count=4,
        policy=MixdepthSelectionPolicy.BALANCED,
    ) == [1, 2, 0, 3]


def test_concentrated_selects_after_largest_cyclic_gap() -> None:
    """The first candidate is the legacy selector's largest-gap endpoint."""
    assert mixdepth_attempt_order(
        {0: 1, 3: 1},
        mixdepth_count=5,
        policy=MixdepthSelectionPolicy.CONCENTRATED,
    ) == [3, 0]


def test_concentrated_preserves_legacy_first_tie_and_recomputes_fallbacks() -> None:
    """Equal gaps select the first sorted endpoint before each recalculation."""
    assert mixdepth_attempt_order(
        {0: 1, 2: 1, 3: 1},
        mixdepth_count=5,
        policy=MixdepthSelectionPolicy.CONCENTRATED,
    ) == [0, 2, 3]


def test_concentrated_matches_reference_for_every_five_depth_subset() -> None:
    """Every possible eligibility shape has the reference first candidate."""
    expected = {
        (0,): 0,
        (1,): 1,
        (2,): 2,
        (3,): 3,
        (4,): 4,
        (0, 1): 0,
        (0, 2): 0,
        (0, 3): 3,
        (0, 4): 4,
        (1, 2): 1,
        (1, 3): 1,
        (1, 4): 4,
        (2, 3): 2,
        (2, 4): 2,
        (3, 4): 3,
        (0, 1, 2): 0,
        (0, 1, 3): 0,
        (0, 1, 4): 4,
        (0, 2, 3): 0,
        (0, 2, 4): 2,
        (0, 3, 4): 3,
        (1, 2, 3): 1,
        (1, 2, 4): 1,
        (1, 3, 4): 1,
        (2, 3, 4): 2,
        (0, 1, 2, 3): 0,
        (0, 1, 2, 4): 4,
        (0, 1, 3, 4): 3,
        (0, 2, 3, 4): 2,
        (1, 2, 3, 4): 1,
        (0, 1, 2, 3, 4): 0,
    }

    for eligible, first_candidate in expected.items():
        order = mixdepth_attempt_order(
            dict.fromkeys(eligible, 1),
            mixdepth_count=5,
            policy=MixdepthSelectionPolicy.CONCENTRATED,
        )
        assert order[0] == first_candidate, eligible


def test_concentrated_supports_one_mixdepth() -> None:
    """The cyclic selector has a valid self-wrapping interval at depth zero."""
    assert mixdepth_attempt_order(
        {0: 1},
        mixdepth_count=1,
        policy=MixdepthSelectionPolicy.CONCENTRATED,
    ) == [0]


@pytest.mark.parametrize(
    ("eligible_mixdepths", "mixdepth_count", "match"),
    [
        ({0: 1}, 0, "positive integer"),
        ({1: 1}, 1, "outside"),
        ({-1: 1}, 1, "outside"),
        ({0: -1}, 1, "non-negative"),
    ],
)
def test_attempt_order_rejects_inconsistent_inputs(
    eligible_mixdepths: dict[int, int], mixdepth_count: int, match: str
) -> None:
    """Invalid internal state cannot produce an out-of-range candidate."""
    with pytest.raises(ValueError, match=match):
        mixdepth_attempt_order(
            eligible_mixdepths,
            mixdepth_count=mixdepth_count,
            policy=MixdepthSelectionPolicy.CONCENTRATED,
        )
