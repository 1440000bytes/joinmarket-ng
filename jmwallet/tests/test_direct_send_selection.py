"""Focused tests for fee-aware, privacy-preserving direct-send selection."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from jmwallet.wallet.coin_selection import DirectSendSearchLimitError, select_direct_send_utxos
from jmwallet.wallet.models import UTXOInfo

DESTINATION = "bcrt1qq6hag67dl53wl99vzg42z8eyzfz2xlkvwk6f7m"


def _utxo(
    value: int,
    script: str,
    *,
    index: int,
    mixdepth: int = 1,
    confirmations: int = 6,
    frozen: bool = False,
    fidelity_bond: bool = False,
    coinjoin_output: bool = False,
) -> UTXOInfo:
    return UTXOInfo(
        txid=f"{index:064x}",
        vout=0,
        value=value,
        address=DESTINATION,
        confirmations=confirmations,
        scriptpubkey=f"0014{script * 20}",
        path=f"m/84'/1'/{mixdepth}'/0/{index}",
        mixdepth=mixdepth,
        frozen=frozen,
        locktime=1 if fidelity_bond else None,
        coinjoin_output=coinjoin_output,
    )


def _select(utxos: list[UTXOInfo], amount: int, *, mixdepth: int = 1, fee_rate: float = 1.0):
    return select_direct_send_utxos(
        utxos, amount, DESTINATION, fee_rate, mixdepth=mixdepth
    )


def test_selects_smallest_sufficient_singleton() -> None:
    small = _utxo(100_000, "a", index=1)
    large = _utxo(120_000, "b", index=2)

    selection = _select([large, small], 90_000)

    assert selection.utxos == [small]


def test_combines_script_groups_only_when_needed() -> None:
    first = _utxo(60_000, "a", index=1)
    second = _utxo(60_000, "b", index=2)

    selection = _select([first, second], 100_000)

    assert selection.utxos == [first, second]


def test_reused_script_cluster_is_atomic() -> None:
    first = _utxo(60_000, "a", index=1)
    second = _utxo(60_000, "a", index=2)

    selection = _select([second, first], 100_000)

    assert selection.utxos == [first, second]


def test_singleton_beats_lower_value_reused_cluster_on_input_count() -> None:
    reused_first = _utxo(55_000, "a", index=1)
    reused_second = _utxo(55_000, "a", index=2)
    singleton = _utxo(120_000, "b", index=3)

    selection = _select([reused_first, singleton, reused_second], 100_000)

    assert selection.utxos == [singleton]


def test_partial_regular_script_cluster_is_blocked() -> None:
    eligible = _utxo(150_000, "a", index=1)
    frozen = _utxo(1_000, "a", index=2, frozen=True)

    with pytest.raises(ValueError, match="No eligible direct-send"):
        _select([eligible, frozen], 100_000)


def test_underconfirmed_script_sibling_blocks_partial_cluster() -> None:
    eligible = _utxo(150_000, "a", index=1)
    unconfirmed = _utxo(1_000, "a", index=2, confirmations=0)

    with pytest.raises(ValueError, match="No eligible direct-send"):
        _select([eligible, unconfirmed], 100_000)


def test_search_limit_fails_instead_of_returning_non_optimal_baseline() -> None:
    larger = _utxo(120_000, "a", index=1)
    smaller = _utxo(101_000, "b", index=2)

    with pytest.raises(DirectSendSearchLimitError, match="before proving an optimal"):
        select_direct_send_utxos(
            [larger, smaller],
            100_000,
            DESTINATION,
            1.0,
            mixdepth=1,
            max_search_nodes=1,
        )


def test_md0_rejects_unrelated_non_coinjoin_clusters() -> None:
    first = _utxo(60_000, "a", index=1, mixdepth=0)
    second = _utxo(60_000, "b", index=2, mixdepth=0)

    with pytest.raises(ValueError, match="multiple script clusters require exact CoinJoin"):
        _select([first, second], 100_000, mixdepth=0)


def test_md0_allows_multiple_exact_coinjoin_clusters() -> None:
    first = _utxo(60_000, "a", index=1, mixdepth=0, coinjoin_output=True)
    second = _utxo(60_000, "b", index=2, mixdepth=0, coinjoin_output=True)

    selection = _select([first, second], 100_000, mixdepth=0)

    assert selection.utxos == [first, second]


def test_md0_does_not_prefer_coinjoin_provenance_among_single_clusters() -> None:
    coinjoin = _utxo(130_000, "a", index=1, mixdepth=0, coinjoin_output=True)
    regular = _utxo(120_000, "b", index=2, mixdepth=0)

    selection = _select([coinjoin, regular], 100_000, mixdepth=0)

    assert selection.utxos == [regular]


@pytest.mark.parametrize(
    "make_unavailable",
    [
        lambda: _utxo(200_000, "a", index=1, frozen=True),
        lambda: _utxo(200_000, "a", index=1, fidelity_bond=True),
        lambda: _utxo(200_000, "a", index=1, confirmations=0),
    ],
)
def test_ineligible_utxos_are_not_selected(
    make_unavailable: Callable[[], UTXOInfo],
) -> None:
    unavailable = make_unavailable()
    fallback = _utxo(120_000, "b", index=2)

    selection = _select([unavailable, fallback], 100_000)

    assert selection.utxos == [fallback]


def test_fee_aware_selection_skips_nominally_sufficient_utxo() -> None:
    nominal = _utxo(100_500, "a", index=1)
    sufficient = _utxo(102_000, "b", index=2)

    selection = _select([nominal, sufficient], 100_000, fee_rate=10.0)

    assert selection.utxos == [sufficient]


def test_dust_change_becomes_fee_with_no_change_output() -> None:
    # One P2WPKH input/output is 110 vB at 1 sat/vB. Adding a change output
    # costs 31 vB, leaving 545 sats, which is below the configured dust floor.
    utxo = _utxo(100_655, "a", index=1)

    selection = _select([utxo], 100_000)

    assert selection.utxos == [utxo]
    assert selection.change_amount == 0
    assert selection.fee == 655
    assert selection.vsize == 110


def test_e13fc3_synthetic_wallet_prefers_2080858_singleton() -> None:
    """Mirror the relevant values/scripts from the reported direct-send case."""
    reused_first = _utxo(550_000, "a", index=1)
    reused_second = _utxo(550_000, "a", index=2)
    target = _utxo(2_080_858, "b", index=int("e13fc3", 16))
    smaller = _utxo(900_000, "c", index=4)

    selection = _select([reused_first, target, smaller, reused_second], 1_000_000)

    assert selection.utxos == [target]
