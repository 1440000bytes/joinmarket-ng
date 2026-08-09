"""Pure liquidity calculations shared by maker offer creation and filling."""

from __future__ import annotations

from decimal import Decimal

from jmcore.constants import DUST_THRESHOLD, MAX_MONEY
from jmcore.models import Offer, calculate_cj_fee, is_absolute_offer_type


def required_maker_input(offer: Offer, cj_amount: int) -> int:
    """Return the maker input value needed for a CoinJoin amount.

    The result includes the maker's transaction fee contribution and reserves
    ``DUST_THRESHOLD + 1`` sats for the mandatory maker change output.
    """
    return (
        cj_amount
        + offer.txfee
        + DUST_THRESHOLD
        + 1
        - calculate_cj_fee(offer.ordertype, offer.cjfee, cj_amount)
    )


def max_fillable_cj_amount(offer: Offer, max_balance: int) -> int | None:
    """Return the greatest valid CoinJoin amount fillable by ``max_balance``.

    Relative fees use the exact Decimal half-even rounding used at fill time.
    Bitcoin's ``MAX_MONEY`` bounds otherwise unbounded high-fee offers.
    """
    if max_balance < 0:
        raise ValueError(f"max_balance must be non-negative, got {max_balance}")

    maximum_required = required_maker_input(offer, MAX_MONEY)
    if is_absolute_offer_type(offer.ordertype):
        if required_maker_input(offer, 0) > max_balance:
            return None
    else:
        fee_rate = Decimal(str(offer.cjfee))
        if fee_rate > 1:
            return MAX_MONEY if maximum_required <= max_balance else None
        if required_maker_input(offer, 0) > max_balance:
            return None

    if maximum_required <= max_balance:
        return MAX_MONEY

    low = 0
    high = MAX_MONEY
    while low < high:
        midpoint = (low + high + 1) // 2
        if required_maker_input(offer, midpoint) <= max_balance:
            low = midpoint
        else:
            high = midpoint - 1
    return low
