"""Tests for routine wallet synchronization log levels."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from _jmwallet_test_helpers import TEST_BOND_ADDRESS, TEST_BOND_LOCKTIME
from loguru import logger

from jmwallet.backends.base import UTXO
from jmwallet.backends.descriptor_wallet import DescriptorWalletBackend
from jmwallet.wallet.service import WalletService


@contextmanager
def _captured_logs() -> Generator[list[tuple[str, str]], None, None]:
    records: list[tuple[str, str]] = []
    sink_id = logger.add(
        lambda message: records.append((message.record["level"].name, message.record["message"])),
        level="DEBUG",
    )
    try:
        yield records
    finally:
        logger.remove(sink_id)


def _assert_debug_only(records: list[tuple[str, str]], fragments: list[str]) -> None:
    for fragment in fragments:
        levels = [level for level, message in records if fragment in message]
        assert levels, f"Expected a log containing {fragment!r}"
        assert set(levels) == {"DEBUG"}


@pytest.mark.asyncio
async def test_legacy_sync_summaries_are_debug(test_mnemonic: str) -> None:
    backend = MagicMock()
    backend.supports_descriptor_scan = False
    backend.supports_watch_address = False
    wallet = WalletService(test_mnemonic, backend, network="regtest", mixdepth_count=1)
    wallet.sync_mixdepth = AsyncMock(return_value=[])  # type: ignore[method-assign]

    with _captured_logs() as records:
        await wallet.sync_all()
        await wallet.sync_all()

    _assert_debug_only(records, ["Syncing all mixdepths", "Sync complete: 0 total UTXOs"])


@pytest.mark.asyncio
async def test_descriptor_scan_summaries_are_debug(test_mnemonic: str) -> None:
    backend = MagicMock()
    backend.supports_descriptor_scan = True
    backend.supports_watch_address = False
    backend.get_block_height = AsyncMock(return_value=100)
    backend.scan_descriptors = AsyncMock(return_value={"success": True, "unspents": []})
    wallet = WalletService(
        test_mnemonic,
        backend,
        network="regtest",
        mixdepth_count=1,
        scan_range=1,
    )

    with _captured_logs() as records:
        await wallet.sync_all()
        await wallet.sync_all()

    _assert_debug_only(records, ["Syncing all mixdepths", "Descriptor sync complete"])


@pytest.mark.asyncio
async def test_loaded_descriptor_wallet_sync_summaries_are_debug(test_mnemonic: str) -> None:
    backend = DescriptorWalletBackend(wallet_name="test_sync_logging")
    backend._wallet_loaded = True
    backend._descriptors_imported = True
    backend.get_max_descriptor_range = AsyncMock(return_value=-1)  # type: ignore[method-assign]
    backend.get_all_utxos = AsyncMock(return_value=[])  # type: ignore[method-assign]
    backend.get_addresses_with_history = AsyncMock(return_value=set())  # type: ignore[method-assign]
    wallet = WalletService(test_mnemonic, backend, network="regtest", mixdepth_count=1)
    wallet.check_and_upgrade_descriptor_range = AsyncMock(  # type: ignore[method-assign]
        return_value=False
    )

    try:
        with _captured_logs() as records:
            await wallet.sync_with_descriptor_wallet()
            await wallet.sync_with_descriptor_wallet()
    finally:
        await backend.close()

    _assert_debug_only(
        records,
        ["Syncing via descriptor wallet", "Descriptor wallet sync complete"],
    )


@pytest.mark.asyncio
async def test_rediscovered_fidelity_bond_logs_are_debug(test_mnemonic: str) -> None:
    backend = MagicMock()
    backend.supports_watch_address = False
    backend.get_utxos = AsyncMock(
        return_value=[
            UTXO(
                txid="ab" * 32,
                vout=0,
                value=1_000_000,
                address=TEST_BOND_ADDRESS,
                confirmations=6,
                scriptpubkey="0020" + "cd" * 32,
                height=100,
            )
        ]
    )
    wallet = WalletService(test_mnemonic, backend, network="mainnet", mixdepth_count=1)
    bond = (TEST_BOND_ADDRESS, TEST_BOND_LOCKTIME, 0)

    with _captured_logs() as records:
        await wallet.sync_fidelity_bonds([TEST_BOND_LOCKTIME], bond_addresses=[bond])
        await wallet.sync_fidelity_bonds([TEST_BOND_LOCKTIME], bond_addresses=[bond])

    _assert_debug_only(records, ["Found fidelity bond UTXO:", "Found 1 fidelity bond UTXOs"])
