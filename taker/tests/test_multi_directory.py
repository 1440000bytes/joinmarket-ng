"""
Unit tests for multi-directory offer verification
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from jmcore.crypto import NickIdentity
from jmcore.directory_client import DirectoryClient
from jmcore.models import Offer, OfferType

from taker.multi_directory import MultiDirectoryClient


@pytest.fixture
def mock_offers() -> list[Offer]:
    return [
        Offer(
            counterparty="maker1",
            oid=0,
            ordertype=OfferType.SW0_RELATIVE,
            minsize=10000,
            maxsize=1000000,
            txfee=1000,
            cjfee="0.001",
        ),
        Offer(
            counterparty="maker2",
            oid=0,
            ordertype=OfferType.SW0_RELATIVE,
            minsize=10000,
            maxsize=1000000,
            txfee=1000,
            cjfee="0.002",
        ),
        Offer(
            counterparty="maker_attacker",
            oid=0,
            ordertype=OfferType.SW0_RELATIVE,
            minsize=10000,
            maxsize=1000000,
            txfee=1000,
            cjfee="0.001",
        ),
    ]


@pytest.fixture
def multi_directory_client() -> MultiDirectoryClient:
    nick_identity = MagicMock(spec=NickIdentity)
    nick_identity.nick = "taker"
    client = MultiDirectoryClient(
        directory_servers=["dir1.test", "dir2.test"],
        network="regtest",
        nick_identity=nick_identity,
    )

    client1 = MagicMock(spec=DirectoryClient)
    client1.host = "dir1.test"
    client1.fetch_orderbooks = AsyncMock(return_value=([], {}))

    client2 = MagicMock(spec=DirectoryClient)
    client2.host = "dir2.test"
    client2.fetch_orderbooks = AsyncMock(return_value=([], {}))

    client.clients = {"dir1.test": client1, "dir2.test": client2}
    return client


@pytest.mark.asyncio
async def test_fetch_orderbook_min_directory_confirmations_1(
    multi_directory_client: MultiDirectoryClient, mock_offers: list[Offer]
) -> None:
    """Test fetch_orderbook with min_directory_confirmations=1 (default behavior)"""
    multi_directory_client.clients["dir1.test"].fetch_orderbooks.return_value = (mock_offers, {})
    multi_directory_client.clients["dir2.test"].fetch_orderbooks.return_value = (
        mock_offers[:2],
        {},
    )

    offers = await multi_directory_client.fetch_orderbook(min_directory_confirmations=1)

    assert len(offers) == 3
    nicks = {offer.counterparty for offer in offers}
    assert nicks == {"maker1", "maker2", "maker_attacker"}


@pytest.mark.asyncio
async def test_fetch_orderbook_min_directory_confirmations_2(
    multi_directory_client: MultiDirectoryClient, mock_offers: list[Offer]
) -> None:
    """Test fetch_orderbook filters out offers seen on only one directory."""
    # Offer 1 and 2 are on both directories.
    # Offer 3 (maker_attacker) is only on dir1.
    multi_directory_client.clients["dir1.test"].fetch_orderbooks.return_value = (mock_offers, {})
    multi_directory_client.clients["dir2.test"].fetch_orderbooks.return_value = (
        mock_offers[:2],
        {},
    )

    offers = await multi_directory_client.fetch_orderbook(min_directory_confirmations=2)

    # maker_attacker should be filtered out
    assert len(offers) == 2
    nicks = {offer.counterparty for offer in offers}
    assert nicks == {"maker1", "maker2"}
    assert "maker_attacker" not in nicks


@pytest.mark.asyncio
async def test_fetch_orderbook_handles_identical_offers_from_multiple_servers(
    multi_directory_client: MultiDirectoryClient, mock_offers: list[Offer]
) -> None:
    """Test that it correctly deduplicates equivalent offers if min confirmations is met."""
    offer = mock_offers[0]
    multi_directory_client.clients["dir1.test"].fetch_orderbooks.return_value = ([offer], {})
    multi_directory_client.clients["dir2.test"].fetch_orderbooks.return_value = ([offer], {})

    offers = await multi_directory_client.fetch_orderbook(min_directory_confirmations=2)

    assert len(offers) == 1
    assert offers[0].counterparty == "maker1"
