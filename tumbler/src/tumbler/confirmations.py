"""Helpers for resolving tumbler-broadcast txid confirmations.

The tumbler runner gates each phase on the previous broadcast reaching a
configurable confirmation depth. The default mechanism is
``backend.get_transaction(txid)``, which works for full-node and
mempool-API backends but always returns ``None`` for light clients
(neutrino / BIP158) that can only match watched addresses.

This module provides a watched-address fallback: given a txid, we look
up the CoinJoin history entry recorded when the taker broadcast it, and
ask the backend whether any UTXO under the addresses we own (destination
or change) reports the same txid. The UTXO's ``confirmations`` field is
the answer.

This keeps the runner's signature simple (it only needs an
``async (txid) -> int | None`` callback), while letting the daemon and
CLI plug in a richer two-stage resolver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from loguru import logger


class _BackendLike(Protocol):
    """Minimal subset of :class:`jmwallet.backends.base.Backend` we use."""

    async def get_transaction(self, txid: str) -> Any: ...

    async def get_utxos(self, addresses: list[str]) -> Any: ...


async def confirmations_from_history(
    txid: str,
    backend: _BackendLike,
    data_dir: Path | None,
) -> int | None:
    """Resolve confirmation count for ``txid`` via watched addresses.

    Looks up the CoinJoin history entry for ``txid`` (recorded by the
    taker on broadcast), then queries ``backend.get_utxos`` against the
    destination and change addresses recorded in that entry. Any UTXO
    whose ``txid`` matches is the broadcast we made; its
    ``confirmations`` field is returned.

    Returns:
        - confirmations (>= 0) if a matching UTXO is found.
        - ``None`` when there is no history entry to consult, or no live
          UTXO matches the txid (caller should fall back to the runner's
          strict-unknown-timeout path).

    The function never raises: backend / history I/O failures are
    logged at debug level and reported as ``None`` so the runner can
    keep polling.
    """
    try:
        from jmwallet.history import read_history
    except Exception:
        logger.debug("jmwallet.history unavailable; cannot resolve transaction via addresses")
        logger.bind(sensitive=True).debug("Cannot resolve {} via addresses", txid)
        return None
    try:
        entries = read_history(data_dir)
    except Exception:
        logger.debug("History read failed while resolving transaction")
        logger.bind(sensitive=True).debug("History read failed while resolving txid {}", txid)
        return None
    addresses: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if getattr(entry, "txid", None) != txid:
            continue
        for addr in (
            getattr(entry, "destination_address", "") or "",
            getattr(entry, "change_address", "") or "",
        ):
            if addr and addr not in seen:
                seen.add(addr)
                addresses.append(addr)
    if not addresses:
        return None
    try:
        utxos = await backend.get_utxos(addresses)
    except Exception:
        logger.debug("Watched-address lookup failed while resolving transaction")
        logger.bind(sensitive=True).debug("get_utxos failed while resolving txid {}", txid)
        return None
    for utxo in utxos or []:
        if getattr(utxo, "txid", None) == txid:
            confirmations = int(getattr(utxo, "confirmations", 0) or 0)
            return confirmations
    # The history entry identifies addresses to inspect, not a currently
    # resolvable transaction. An evicted or never-confirmed broadcast has no
    # live matching UTXO, so let the runner's unknown-confirmation timeout
    # bound the wait rather than treating it as a known zero-confirmation tx.
    return None


async def resolve_confirmations(
    txid: str,
    backend: _BackendLike,
    data_dir: Path | None,
) -> int | None:
    """Two-stage confirmation resolver suitable for ``RunnerContext.get_confirmations``.

    1. Try ``backend.get_transaction(txid)`` (works for full nodes /
       mempool.space backends).
    2. If that returns ``None``, fall back to
       :func:`confirmations_from_history`.

    Errors at either stage are swallowed and reported as ``None`` so the
    runner can keep polling.
    """
    try:
        tx = await backend.get_transaction(txid)
    except Exception:
        logger.error("Confirmation lookup backend error")
        logger.bind(sensitive=True).exception("get_confirmations({}) backend error", txid)
        return None
    if tx is not None:
        return int(getattr(tx, "confirmations", 0) or 0)
    try:
        return await confirmations_from_history(txid, backend, data_dir)
    except Exception:
        logger.error("Confirmation address-lookup fallback error")
        logger.bind(sensitive=True).exception(
            "get_confirmations({}) address-lookup fallback error", txid
        )
        return None
