"""Certificate expiry tests for orderbook watcher bond valuation."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from jmcore.models import FidelityBond, Offer, OfferType, OrderBook
from jmwallet.backends.base import BondVerificationResult

from orderbook_watcher.aggregator import OrderbookAggregator

TEST_PUBKEY_HEX = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
OTHER_PUBKEY_HEX = "02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5"
CURRENT_BLOCK_HEIGHT = 900_000
CERT_EXPIRY = 901_152


def _bond(
    *,
    txid: str = "a" * 64,
    vout: int = 0,
    counterparty: str = "Maker1",
    pubkey: str = TEST_PUBKEY_HEX,
    cert_expiry: int = CERT_EXPIRY,
    bond_value: int | None = None,
) -> FidelityBond:
    locktime = int(time.time()) + 31_536_000
    bond_data = {
        "maker_nick": counterparty,
        "utxo_txid": txid,
        "utxo_vout": vout,
        "locktime": locktime,
        "utxo_pub": pubkey,
        "cert_expiry": cert_expiry,
    }
    return FidelityBond(
        counterparty=counterparty,
        utxo_txid=txid,
        utxo_vout=vout,
        bond_value=bond_value,
        locktime=locktime,
        amount=0,
        script=pubkey,
        utxo_confirmations=0,
        cert_expiry=cert_expiry,
        fidelity_bond_data=bond_data,
    )


def _offer(bond: FidelityBond, *, oid: int, cert_expiry: int | None = None) -> Offer:
    bond_data = dict(bond.fidelity_bond_data or {})
    if cert_expiry is not None:
        bond_data["cert_expiry"] = cert_expiry
    return Offer(
        counterparty=bond.counterparty,
        oid=oid,
        ordertype=OfferType.SW0_RELATIVE,
        minsize=10_000,
        maxsize=1_000_000,
        txfee=1000,
        cjfee="0.001",
        fidelity_bond_data=bond_data,
    )


def _aggregator(backend: AsyncMock) -> OrderbookAggregator:
    return OrderbookAggregator(
        directory_nodes=[],
        network="mainnet",
        mempool_api_url="",
        blockchain_backend=backend,
    )


def _valid_result(bond: FidelityBond) -> BondVerificationResult:
    return BondVerificationResult(
        txid=bond.utxo_txid,
        vout=bond.utxo_vout,
        value=1_000_000_000,
        confirmations=10_000,
        block_time=int(time.time()) - (10_000 * 600),
        valid=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_block_height", "expected_valid"),
    [
        (CERT_EXPIRY - 1, True),
        (CERT_EXPIRY, True),
        (CERT_EXPIRY + 1, False),
    ],
)
async def test_certificate_expiry_reference_boundary(
    current_block_height: int, expected_valid: bool
) -> None:
    backend = AsyncMock()
    backend.get_block_height.return_value = current_block_height
    bond = _bond()
    backend.verify_bonds.return_value = [_valid_result(bond)]
    aggregator = _aggregator(backend)
    orderbook = OrderBook(fidelity_bonds=[bond])

    await aggregator._calculate_bond_values(orderbook)

    assert orderbook.current_block_height == current_block_height
    if expected_valid:
        assert bond.bond_value is not None and bond.bond_value > 0
        backend.verify_bonds.assert_awaited_once()
    else:
        assert bond.bond_value == 0
        backend.verify_bonds.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_height", [None, "900000", -1, True])
async def test_invalid_height_fails_closed(invalid_height: object) -> None:
    backend = AsyncMock()
    backend.get_block_height.return_value = invalid_height
    bond = _bond(bond_value=123)
    aggregator = _aggregator(backend)
    orderbook = OrderBook(fidelity_bonds=[bond])

    await aggregator._calculate_bond_values(orderbook)

    assert orderbook.current_block_height is None
    assert bond.bond_value is None
    backend.verify_bonds.assert_not_awaited()


@pytest.mark.asyncio
async def test_height_failure_clears_cached_value() -> None:
    backend = AsyncMock()
    backend.get_block_height.side_effect = RuntimeError("backend unavailable")
    bond = _bond(bond_value=123)
    aggregator = _aggregator(backend)
    orderbook = OrderBook(fidelity_bonds=[bond])

    await aggregator._calculate_bond_values(orderbook)

    assert bond.bond_value is None
    backend.verify_bonds.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_cached_value_is_cleared() -> None:
    backend = AsyncMock()
    backend.get_block_height.return_value = CERT_EXPIRY + 1
    aggregator = _aggregator(backend)
    cached_bond = _bond(bond_value=123)
    cache_key = aggregator._bond_claim_key(cached_bond)
    aggregator._bond_cache[cache_key] = cached_bond
    bond = _bond()
    orderbook = OrderBook(fidelity_bonds=[bond])

    aggregator._apply_bond_cache(orderbook)
    await aggregator._calculate_bond_values(orderbook)

    assert bond.bond_value == 0
    assert cache_key not in aggregator._bond_cache
    backend.verify_bonds.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_value_is_not_cached_across_certificate_renewal() -> None:
    backend = AsyncMock()
    backend.get_block_height.return_value = CERT_EXPIRY + 1
    aggregator = _aggregator(backend)
    expired = _bond(cert_expiry=CERT_EXPIRY)
    expired_orderbook = OrderBook(fidelity_bonds=[expired])

    await aggregator._calculate_bond_values(expired_orderbook)
    aggregator._update_bond_cache(expired_orderbook)

    cache_key = aggregator._bond_claim_key(expired)
    assert expired.bond_value == 0
    assert cache_key not in aggregator._bond_cache

    renewed = _bond(cert_expiry=CERT_EXPIRY + 2016)
    backend.verify_bonds.return_value = [_valid_result(renewed)]
    renewed_orderbook = OrderBook(fidelity_bonds=[renewed])
    aggregator._apply_bond_cache(renewed_orderbook)
    await aggregator._calculate_bond_values(renewed_orderbook)

    assert renewed.bond_value is not None and renewed.bond_value > 0
    backend.verify_bonds.assert_awaited_once()


def test_deduplication_keeps_newest_certificate_for_same_claim() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    expired = _bond(cert_expiry=CERT_EXPIRY - 2016)
    renewed = _bond(cert_expiry=CERT_EXPIRY)
    orderbook = OrderBook(fidelity_bonds=[expired, renewed])

    aggregator._deduplicate_bonds(orderbook)

    assert orderbook.fidelity_bonds == [renewed]


def test_offer_deduplication_prefers_renewed_certificate_over_later_stale_copy() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    bond = _bond()
    renewed = _offer(bond, oid=0, cert_expiry=CERT_EXPIRY)
    stale = _offer(bond, oid=0, cert_expiry=CERT_EXPIRY - 2016)
    renewed.directory_node = "dir1"
    stale.directory_node = "dir2"
    bond_key = f"{bond.utxo_txid}:{bond.utxo_vout}"

    deduplicated = aggregator._deduplicate_bond_backed_offers(
        [
            (renewed, 1000.0, bond_key, "dir1"),
            (stale, 2000.0, bond_key, "dir2"),
        ]
    )

    assert deduplicated == [renewed]
    assert set(renewed.directory_nodes) == {"dir1", "dir2"}


def test_same_nick_renewal_keeps_both_directory_attributions() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    bond = _bond()
    stale = _offer(bond, oid=0, cert_expiry=CERT_EXPIRY - 2016)
    renewed = _offer(bond, oid=0, cert_expiry=CERT_EXPIRY)
    stale.directory_node = "dir1"
    renewed.directory_node = "dir2"
    bond_key = f"{bond.utxo_txid}:{bond.utxo_vout}"

    deduplicated = aggregator._deduplicate_bond_backed_offers(
        [
            (stale, 1000.0, bond_key, "dir1"),
            (renewed, 1005.0, bond_key, "dir2"),
        ]
    )

    assert deduplicated == [renewed]
    assert set(renewed.directory_nodes) == {"dir1", "dir2"}


def test_cross_nick_renewal_survives_deduplication_and_linking() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    expired_bond = _bond(counterparty="OldMaker", cert_expiry=CURRENT_BLOCK_HEIGHT - 1)
    renewed_data = dict(expired_bond.fidelity_bond_data or {})
    renewed_data.update({"maker_nick": "NewMaker", "cert_expiry": CERT_EXPIRY})
    renewed_bond = expired_bond.model_copy(
        update={
            "counterparty": "NewMaker",
            "cert_expiry": CERT_EXPIRY,
            "fidelity_bond_data": renewed_data,
            "bond_value": 123,
        }
    )
    expired_offer = _offer(expired_bond, oid=0)
    renewed_offer = _offer(renewed_bond, oid=0)
    bond_key = f"{expired_bond.utxo_txid}:{expired_bond.utxo_vout}"

    offers = aggregator._deduplicate_bond_backed_offers(
        [
            (expired_offer, 1000.0, bond_key, "dir1"),
            (renewed_offer, 1005.0, bond_key, "dir2"),
        ]
    )
    orderbook = OrderBook(
        offers=offers,
        fidelity_bonds=[expired_bond, renewed_bond],
        current_block_height=CURRENT_BLOCK_HEIGHT,
    )
    aggregator._deduplicate_bonds(orderbook)
    aggregator._link_bonds_to_offers(orderbook)

    assert orderbook.fidelity_bonds == [renewed_bond]
    assert offers == [renewed_offer]
    assert renewed_offer.fidelity_bond_value == 123


def test_higher_expiry_conflicting_claim_cannot_suppress_valid_offer() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    valid_bond = _bond(cert_expiry=CERT_EXPIRY)
    conflicting_bond = _bond(
        counterparty="ConflictingMaker",
        pubkey=OTHER_PUBKEY_HEX,
        cert_expiry=CERT_EXPIRY + 2016,
    )
    valid_offer = _offer(valid_bond, oid=0)
    conflicting_offer = _offer(conflicting_bond, oid=0)
    bond_key = f"{valid_bond.utxo_txid}:{valid_bond.utxo_vout}"

    deduplicated = aggregator._deduplicate_bond_backed_offers(
        [
            (valid_offer, 1000.0, bond_key, "dir1"),
            (conflicting_offer, 1005.0, bond_key, "dir2"),
        ]
    )

    assert deduplicated == [valid_offer, conflicting_offer]


def test_expired_offer_cannot_inherit_renewed_bond_value() -> None:
    backend = AsyncMock()
    aggregator = _aggregator(backend)
    bond = _bond(bond_value=123)
    expired_offer = _offer(bond, oid=0, cert_expiry=CURRENT_BLOCK_HEIGHT - 1)
    valid_offer = _offer(bond, oid=1, cert_expiry=CERT_EXPIRY)
    orderbook = OrderBook(
        offers=[expired_offer, valid_offer],
        fidelity_bonds=[bond],
        current_block_height=CURRENT_BLOCK_HEIGHT,
    )

    aggregator._link_bonds_to_offers(orderbook)

    assert expired_offer.fidelity_bond_value == 0
    assert valid_offer.fidelity_bond_value == 123


@pytest.mark.asyncio
async def test_conflicting_script_claims_are_verified_independently() -> None:
    backend = AsyncMock()
    backend.get_block_height.return_value = CURRENT_BLOCK_HEIGHT
    invalid_bond = _bond(pubkey=OTHER_PUBKEY_HEX)
    valid_bond = _bond(pubkey=TEST_PUBKEY_HEX)
    backend.verify_bonds.return_value = [
        BondVerificationResult(
            txid=invalid_bond.utxo_txid,
            vout=invalid_bond.utxo_vout,
            value=0,
            confirmations=0,
            block_time=0,
            valid=False,
            error="ScriptPubKey mismatch",
        ),
        _valid_result(valid_bond),
    ]
    aggregator = _aggregator(backend)
    orderbook = OrderBook(fidelity_bonds=[invalid_bond, valid_bond])
    aggregator._deduplicate_bonds(orderbook)

    await aggregator._calculate_bond_values(orderbook)

    requests = backend.verify_bonds.call_args.args[0]
    assert len(requests) == 2
    assert requests[0].scriptpubkey != requests[1].scriptpubkey
    assert invalid_bond.bond_value is None
    assert valid_bond.bond_value is not None and valid_bond.bond_value > 0
