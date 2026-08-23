"""Shared minimum miner-fee policy for CoinJoin participants."""

from __future__ import annotations

import math
from inspect import isawaitable
from typing import Any

from loguru import logger


def estimate_p2wpkh_vsize(num_inputs: int, num_outputs: int) -> int:
    """Return the conservative P2WPKH virtual-size estimate used by CoinJoin."""
    return num_inputs * 68 + num_outputs * 31 + 11


def fee_rate_meets_minimum(fee: int, vsize: int, minimum_fee_rate: float) -> bool:
    """Check whether an integer fee meets the exact minimum fee rate."""
    return fee >= 0 and vsize > 0 and fee >= minimum_fee_rate * vsize


def _is_finite_positive(value: object) -> bool:
    """Return whether a runtime policy value is a finite positive number."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


async def resolve_min_fee_rate(
    backend: Any,
    *,
    static_floor: float,
    block_target: int,
    max_fee_rate: float,
) -> float:
    """Resolve the bounded maximum of static, mempool, and estimate fee floors."""
    if not _is_finite_positive(static_floor):
        raise ValueError("Minimum fee static floor must be a finite positive sat/vB value")
    if not _is_finite_positive(max_fee_rate):
        raise ValueError("Maximum fee rate must be a finite positive sat/vB value")
    sources = [static_floor]

    try:
        mempool_minimum = await backend.get_mempool_min_fee()
        if mempool_minimum is not None:
            if _is_finite_positive(mempool_minimum):
                sources.append(mempool_minimum)
            else:
                logger.warning("Ignoring invalid local mempool minimum fee rate")
    except Exception as exc:
        logger.warning(f"Could not resolve local mempool minimum fee rate: {exc}")

    try:
        can_estimate = backend.can_estimate_fee()
        if isawaitable(can_estimate):
            can_estimate = await can_estimate
        if can_estimate:
            estimate = await backend.estimate_fee(block_target)
            if _is_finite_positive(estimate):
                sources.append(estimate)
            else:
                logger.warning("Ignoring invalid fee estimate for minimum miner-fee policy")
    except Exception as exc:
        logger.warning(f"Could not resolve fee estimate for minimum miner-fee policy: {exc}")

    return min(max(sources), max_fee_rate)
