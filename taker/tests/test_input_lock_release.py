"""Persisted input locks must be released when a coinjoin round fails.

Input locks are persisted to the wallet metadata file with a TTL of several
minutes. A failed ``do_coinjoin`` round that returns without releasing them
would keep the inputs "locked by another in-flight CoinJoin" for the whole
TTL, blocking retries even from fresh Taker instances (which discard the
in-memory reservation but not the on-disk lock). This is exactly what a
tumbler retry loop hits when a phase fails mid-negotiation.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, Mock

import pytest
from _taker_test_helpers import make_taker_config, make_utxo
from jmcore.models import Offer, OfferType

from taker.taker import Taker, TakerState


def _make_wallet(utxos: list) -> AsyncMock:
    wallet = AsyncMock()
    wallet.mixdepth_count = 5
    wallet.get_utxos = AsyncMock(return_value=utxos)
    wallet.get_all_utxos = Mock(return_value=list(utxos))
    wallet.get_locked_input_outpoints = Mock(return_value=set())
    wallet.select_utxos = Mock(return_value=list(utxos))
    wallet.reserve_coinjoin_inputs = Mock(return_value=True)
    wallet.renew_coinjoin_inputs = Mock(return_value=True)
    wallet.release_coinjoin_inputs = Mock()
    return wallet


def _backend() -> AsyncMock:
    backend = AsyncMock()
    backend.can_provide_neutrino_metadata = Mock(return_value=False)
    backend.requires_neutrino_metadata = Mock(return_value=False)
    backend.can_estimate_fee = Mock(return_value=False)
    backend.get_mempool_min_fee = AsyncMock(return_value=None)
    return backend


def _offer(nick: str) -> Offer:
    return Offer(
        counterparty=nick,
        oid=0,
        ordertype=OfferType.SW0_ABSOLUTE,
        minsize=1_000,
        maxsize=100_000_000,
        txfee=0,
        cjfee=500,
    )


@pytest.mark.asyncio
async def test_failure_after_reservation_releases_persisted_locks() -> None:
    """A round that reserves inputs and then fails must release the locks."""
    utxo = make_utxo(txid_char="a", value=25_000_000, confirmations=10)
    wallet = _make_wallet([utxo])
    config = make_taker_config(
        counterparty_count=2,
        minimum_makers=2,
        taker_utxo_age=5,
        taker_utxo_amtpercent=20,
        fee_rate=1.0,
    )
    taker = Taker(wallet, _backend(), config)

    offers = [_offer("J5maker1"), _offer("J5maker2")]
    taker.directory_client.fetch_orderbook = AsyncMock(return_value=offers)
    taker._update_offers_with_bond_values = AsyncMock()  # type: ignore[method-assign]
    taker.orderbook_manager.update_offers = Mock()  # type: ignore[method-assign]
    taker.orderbook_manager.select_makers = Mock(  # type: ignore[method-assign]
        return_value=({o.counterparty: o for o in offers}, 1_000)
    )
    # Fail the round right after the reservation: no PoDLE commitment.
    taker.podle_manager.get_fresh_commitment_utxos = Mock(return_value=[utxo])  # type: ignore[method-assign]
    taker.podle_manager.generate_fresh_commitment = Mock(return_value=None)  # type: ignore[method-assign]

    result = await taker.do_coinjoin(
        amount=5_000_000,
        destination="bcrt1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        mixdepth=0,
    )

    assert result is None
    assert taker.state == TakerState.FAILED
    wallet.reserve_coinjoin_inputs.assert_called_once_with(
        {(utxo.txid, utxo.vout)},
        ttl=taker._session.input_lock_ttl_sec(),
        owner=taker._session.input_lock_owner,
    )
    wallet.release_coinjoin_inputs.assert_called_once_with(
        {(utxo.txid, utxo.vout)}, owner=taker._session.input_lock_owner
    )
    assert taker._session.reserved_inputs == set()


@pytest.mark.asyncio
async def test_initial_confirmation_timeout_stops_before_podle_and_releases_locks() -> None:
    utxo = make_utxo(txid_char="a", value=25_000_000, confirmations=10)
    wallet = _make_wallet([utxo])
    config = make_taker_config(
        counterparty_count=2,
        minimum_makers=2,
        taker_utxo_age=5,
        taker_utxo_amtpercent=20,
        fee_rate=1.0,
    )
    config.initial_confirmation_timeout_sec = 0.01  # type: ignore[assignment]

    async def wait_forever(**kwargs: object) -> bool:
        await asyncio.Event().wait()
        return True

    taker = Taker(wallet, _backend(), config, confirmation_callback=wait_forever)
    offers = [_offer("J5maker1"), _offer("J5maker2")]
    taker.directory_client.fetch_orderbook = AsyncMock(return_value=offers)
    taker._update_offers_with_bond_values = AsyncMock()  # type: ignore[method-assign]
    taker.orderbook_manager.update_offers = Mock()  # type: ignore[method-assign]
    taker.orderbook_manager.select_makers = Mock(  # type: ignore[method-assign]
        return_value=({o.counterparty: o for o in offers}, 1_000)
    )
    taker.podle_manager.get_fresh_commitment_utxos = Mock(return_value=[utxo])  # type: ignore[method-assign]
    taker.podle_manager.generate_fresh_commitment = Mock()  # type: ignore[method-assign]
    taker._run_fill_with_replacements = AsyncMock()  # type: ignore[method-assign]

    result = await taker.do_coinjoin(
        amount=5_000_000,
        destination="bcrt1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        mixdepth=0,
    )

    assert result is None
    assert taker.state == TakerState.CANCELLED
    assert taker.last_failure_reason is not None
    assert "confirmation expired" in taker.last_failure_reason
    taker.podle_manager.generate_fresh_commitment.assert_not_called()
    taker._run_fill_with_replacements.assert_not_awaited()
    wallet.release_coinjoin_inputs.assert_called_once_with(
        {(utxo.txid, utxo.vout)}, owner=taker._session.input_lock_owner
    )
    assert taker._session.reserved_inputs == set()


@pytest.mark.asyncio
async def test_late_synchronous_confirmation_is_rejected() -> None:
    def confirm_after_timeout(**kwargs: object) -> bool:
        time.sleep(0.02)
        return True

    taker = Taker(
        _make_wallet([]),
        _backend(),
        make_taker_config(),
        confirmation_callback=confirm_after_timeout,
    )

    with pytest.raises(TimeoutError):
        await taker._request_confirmation(timeout=0.01, stage="initial")


@pytest.mark.asyncio
async def test_new_round_does_not_release_prior_post_sign_lease() -> None:
    """Fresh round state must not compare-and-release an earlier signed lease."""
    utxo = make_utxo(txid_char="a", value=25_000_000, confirmations=1)  # immature
    wallet = _make_wallet([utxo])
    wallet.select_utxos = Mock(side_effect=ValueError("Insufficient funds"))
    taker = Taker(wallet, _backend(), make_taker_config(taker_utxo_age=5))
    leftover = {("b" * 64, 1)}
    prior_session = taker._session
    prior_owner = prior_session.input_lock_owner
    prior_session.reserved_inputs = set(leftover)
    prior_session.signing_boundary_crossed = True

    result = await taker.do_coinjoin(amount=5_000_000, destination="INTERNAL", mixdepth=0)

    assert result is None
    assert taker._session is not prior_session
    assert taker._session.input_lock_owner != prior_owner
    wallet.release_coinjoin_inputs.assert_not_called()
    wallet.renew_coinjoin_inputs.assert_not_called()
    assert taker._session.reserved_inputs == set()
