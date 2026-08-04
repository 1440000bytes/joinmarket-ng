"""Tests for interactive UTXO selection in the taker.

Covers the full-wallet fetch in ``_maybe_select_utxos_interactively`` and
the mixdepth derivation in ``do_coinjoin`` (the source mixdepth is pinned
to the first selected UTXO when the caller does not set one).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import pytest
from _taker_test_helpers import make_taker_config, make_utxo

from taker.taker import Taker, TakerState


def _make_wallet(utxos_by_md: dict[int, list]) -> AsyncMock:
    wallet = AsyncMock()
    wallet.mixdepth_count = 5
    wallet.wallet_fingerprint = "deadbeef"
    wallet.get_utxos = AsyncMock(side_effect=lambda md: utxos_by_md.get(md, []))
    wallet.get_locked_input_outpoints = Mock(return_value=set())
    wallet.select_utxos = Mock(side_effect=lambda md, *_args, **_kwargs: utxos_by_md.get(md, []))
    wallet.get_new_internal_address = Mock(return_value="bcrt1qinternaldest")
    wallet.reserve_coinjoin_inputs = Mock(return_value=True)
    return wallet


def _make_config(tmp_path: Path, **overrides: object):  # noqa: ANN202
    base: dict[str, object] = {
        "select_utxos": True,
        "taker_utxo_age": 5,
        "data_dir": tmp_path,
    }
    base.update(overrides)
    return make_taker_config(**base)


def _backend() -> AsyncMock:
    backend = AsyncMock()
    backend.can_provide_neutrino_metadata = Mock(return_value=False)
    backend.requires_neutrino_metadata = Mock(return_value=False)
    return backend


@pytest.mark.asyncio
async def test_selector_receives_whole_wallet_and_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All mixdepths are fetched; allowed_mixdepth/min_confirmations forwarded."""
    utxos_by_md = {
        0: [make_utxo(txid_char="a", mixdepth=0, confirmations=10)],
        2: [make_utxo(txid_char="b", mixdepth=2, confirmations=10)],
    }
    taker = Taker(_make_wallet(utxos_by_md), _backend(), _make_config(tmp_path))

    captured: dict[str, object] = {}

    def fake_select(utxos, target_amount=0, allowed_mixdepth=None, min_confirmations=0):  # noqa: ANN001, ANN202
        captured["utxos"] = list(utxos)
        captured["allowed_mixdepth"] = allowed_mixdepth
        captured["min_confirmations"] = min_confirmations
        return [utxos_by_md[2][0]]

    import jmwallet.utxo_selector

    monkeypatch.setattr(jmwallet.utxo_selector, "select_utxos_interactive", fake_select)

    selected = await taker._maybe_select_utxos_interactively(amount=1_000_000, mixdepth=None)

    assert selected == [utxos_by_md[2][0]]
    assert captured["allowed_mixdepth"] is None
    assert captured["min_confirmations"] == 5
    # UTXOs from every mixdepth are shown, not just one.
    shown = captured["utxos"]
    assert isinstance(shown, list)
    assert {u.mixdepth for u in shown} == {0, 2}


@pytest.mark.asyncio
async def test_pinned_mixdepth_without_eligible_utxos_fails(tmp_path: Path) -> None:
    """A pinned mixdepth with only immature UTXOs fails before the TUI opens."""
    utxos_by_md = {
        0: [make_utxo(txid_char="a", mixdepth=0, confirmations=1)],
        1: [make_utxo(txid_char="b", mixdepth=1, confirmations=10)],
    }
    taker = Taker(_make_wallet(utxos_by_md), _backend(), _make_config(tmp_path))

    result = await taker._maybe_select_utxos_interactively(amount=1_000_000, mixdepth=0)

    assert result is None
    assert taker.state == TakerState.FAILED
    assert taker._session.last_failure_reason is not None
    assert "mixdepth 0" in taker._session.last_failure_reason


@pytest.mark.asyncio
async def test_do_coinjoin_derives_mixdepth_from_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source mixdepth (and INTERNAL destination) follow the selection."""
    selected_utxo = make_utxo(txid_char="b", value=25_000_000, mixdepth=2, confirmations=10)
    utxos_by_md = {2: [selected_utxo]}
    wallet = _make_wallet(utxos_by_md)
    backend = _backend()
    backend.get_mempool_min_fee = AsyncMock(return_value=None)
    taker = Taker(wallet, backend, _make_config(tmp_path, fee_rate=2.0))
    taker.directory_client.fetch_orderbook = AsyncMock(return_value=[])
    taker._maybe_select_utxos_interactively = AsyncMock(return_value=[selected_utxo])  # type: ignore[method-assign]

    result = await taker.do_coinjoin(amount=5_000_000, destination="INTERNAL", mixdepth=None)

    # The round fails later for lack of offers, but the source mixdepth was
    # derived from the selection and the INTERNAL destination targets md+1.
    assert result is None
    assert taker.last_source_mixdepth == 2
    wallet.get_new_internal_address.assert_called_once_with(3)
    taker._maybe_select_utxos_interactively.assert_awaited_once_with(
        amount=5_000_000, mixdepth=None
    )


@pytest.mark.asyncio
async def test_one_mixdepth_internal_destination_and_change_are_distinct(tmp_path: Path) -> None:
    """The taker's destination reservation must advance same-branch change."""
    selected_utxo = make_utxo(txid_char="a", value=25_000_000, mixdepth=0, confirmations=10)
    wallet = _make_wallet({0: [selected_utxo]})
    wallet.mixdepth_count = 1
    destination = "bcrt1qqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcruj60yu"
    change = "bcrt1qqgpqyqszqgpqyqszqgpqyqszqgpqyqszazmwwa"
    wallet.get_new_internal_address.side_effect = [destination, change]

    backend = _backend()
    backend.get_mempool_min_fee = AsyncMock(return_value=None)
    taker = Taker(wallet, backend, _make_config(tmp_path, select_utxos=False, fee_rate=1.0))
    taker.directory_client.fetch_orderbook = AsyncMock(return_value=[])

    result = await taker.do_coinjoin(amount=5_000_000, destination="INTERNAL", mixdepth=0)
    assert result is None

    taker._session.preselected_utxos = [selected_utxo]
    taker._session.cj_amount = 5_000_000
    taker._session.is_sweep = False
    taker._session._fee_rate = 1.0
    taker._session.maker_sessions = {}

    assert await taker._session._phase_build_tx(destination=destination, mixdepth=0) is True
    assert taker._session.taker_change_address == change
    assert destination != taker._session.taker_change_address
    assert wallet.get_new_internal_address.call_args_list == [call(0), call(0)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("taker_change", "expected_kept"),
    [(2730, False), (2731, True), (3_000, True)],
)
async def test_build_tx_uses_taker_change_threshold(
    tmp_path: Path, taker_change: int, expected_kept: bool
) -> None:
    """Address allocation and tx building share the taker change cutoff."""
    cj_amount = 1_000_000
    tx_fee = 141  # One P2WPKH input, two outputs, at 1 sat/vB.
    selected_utxo = make_utxo(
        txid_char="a",
        value=cj_amount + tx_fee + taker_change,
        mixdepth=0,
        confirmations=10,
    )
    wallet = _make_wallet({0: [selected_utxo]})
    change_address = "bcrt1qqgpqyqszqgpqyqszqgpqyqszqgpqyqszazmwwa"
    wallet.get_new_internal_address.return_value = change_address

    taker = Taker(wallet, _backend(), _make_config(tmp_path, fee_rate=1.0))
    taker._session.preselected_utxos = [selected_utxo]
    taker._session.cj_amount = cj_amount
    taker._session.is_sweep = False
    taker._session._fee_rate = 1.0
    taker._session._randomized_fee_rate = 1.0
    taker._session.maker_sessions = {}

    result = await taker._session._phase_build_tx(
        destination="bcrt1qqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcruj60yu",
        mixdepth=0,
    )

    assert result is True
    assert (taker._session.taker_change_address == change_address) is expected_kept
    assert (("taker", "change") in taker._session.tx_metadata["output_owners"]) is expected_kept
    if expected_kept:
        wallet.get_new_internal_address.assert_called_once_with(0)
    else:
        wallet.get_new_internal_address.assert_not_called()


@pytest.mark.asyncio
async def test_do_coinjoin_cancelled_selection_stops_before_network(tmp_path: Path) -> None:
    """A cancelled selection aborts before any orderbook fetch."""
    utxos_by_md = {0: [make_utxo(txid_char="a", confirmations=10)]}
    taker = Taker(_make_wallet(utxos_by_md), _backend(), _make_config(tmp_path))
    taker.directory_client.fetch_orderbook = AsyncMock(return_value=[])
    taker._maybe_select_utxos_interactively = AsyncMock(return_value=None)  # type: ignore[method-assign]
    taker.state = TakerState.CANCELLED

    result = await taker.do_coinjoin(amount=5_000_000, destination="INTERNAL", mixdepth=None)

    assert result is None
    taker.directory_client.fetch_orderbook.assert_not_called()
