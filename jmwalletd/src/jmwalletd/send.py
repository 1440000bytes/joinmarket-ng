"""Direct-send helper for jmwalletd.

Thin wrapper around :func:`jmwallet.wallet.spend.direct_send` that adapts the
result for the jmwalletd HTTP API response format.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from jmwallet.wallet.spend import DirectSendResult, direct_send

if TYPE_CHECKING:
    from jmwallet.wallet.service import WalletService


async def do_direct_send(
    *,
    wallet_service: WalletService,
    mixdepth: int,
    amount_sats: int,
    destination: str,
) -> DirectSendResult:
    """Build and broadcast a direct (non-coinjoin) transaction.

    Delegates entirely to :func:`jmwallet.wallet.spend.direct_send`.
    """
    from jmwalletd._backend import get_backend

    data_dir: Path = wallet_service.data_dir or Path.home() / ".joinmarket-ng"
    backend = await get_backend(data_dir)

    # Ensure the wallet is synced before sending.
    await wallet_service.sync()

    logger.info(
        "Direct send: {} sats from mixdepth {} to {}",
        amount_sats or "sweep",
        mixdepth,
        destination,
    )

    return await direct_send(
        wallet=wallet_service,
        backend=backend,
        mixdepth=mixdepth,
        amount_sats=amount_sats,
        destination=destination,
    )
