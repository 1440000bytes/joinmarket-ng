"""Blockchain backend placeholder for wallet operations that require no network access."""

from __future__ import annotations

from jmwallet.backends.base import UTXO, BlockchainBackend, Transaction


class OfflineBackendError(RuntimeError):
    """Raised if an offline wallet operation unexpectedly requests blockchain data."""


class OfflineBackend(BlockchainBackend):
    """Backend that fails closed if code attempts blockchain access."""

    @staticmethod
    def _unavailable() -> OfflineBackendError:
        return OfflineBackendError("Blockchain access is unavailable in offline mode")

    async def get_utxos(self, addresses: list[str]) -> list[UTXO]:
        raise self._unavailable()

    async def get_address_balance(self, address: str) -> int:
        raise self._unavailable()

    async def broadcast_transaction(self, tx_hex: str) -> str:
        raise self._unavailable()

    async def get_transaction(self, txid: str) -> Transaction | None:
        raise self._unavailable()

    async def estimate_fee(self, target_blocks: int) -> float:
        raise self._unavailable()

    async def get_block_height(self) -> int:
        raise self._unavailable()

    async def get_block_time(self, block_height: int) -> int:
        raise self._unavailable()

    async def get_block_hash(self, block_height: int) -> str:
        raise self._unavailable()

    async def get_utxo(self, txid: str, vout: int) -> UTXO | None:
        raise self._unavailable()

    def can_estimate_fee(self) -> bool:
        return False

    def can_lookup_arbitrary_utxos(self) -> bool:
        return False

    def has_mempool_access(self) -> bool:
        return False
