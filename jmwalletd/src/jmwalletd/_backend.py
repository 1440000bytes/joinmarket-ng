"""Blockchain backend factory.

Provides a single ``get_backend()`` coroutine that creates and caches the
blockchain backend (Bitcoin Core RPC, descriptor wallet, etc.) based on the
application configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

_backend_instance: Any = None


async def get_backend(data_dir: Path) -> Any:
    """Return a shared blockchain backend instance.

    Creates the backend on first call based on the JoinMarket settings,
    then caches it for subsequent calls.
    """
    global _backend_instance

    if _backend_instance is not None:
        return _backend_instance

    from jmcore.settings import get_settings

    settings = get_settings()
    backend_type = settings.bitcoin.backend_type

    logger.info("Initializing blockchain backend: {}", backend_type)

    rpc_url = settings.bitcoin.rpc_url
    rpc_user = settings.bitcoin.rpc_user
    # SecretStr -> str for backend constructors.
    raw_password = settings.bitcoin.rpc_password
    rpc_password: str = (
        raw_password.get_secret_value()
        if hasattr(raw_password, "get_secret_value")
        else str(raw_password)
    )

    if backend_type == "descriptor_wallet":
        from jmwallet.backends.descriptor_wallet import DescriptorWalletBackend

        _backend_instance = DescriptorWalletBackend(
            rpc_url=rpc_url,
            rpc_user=rpc_user,
            rpc_password=rpc_password,
        )
    elif backend_type == "scantxoutset":
        from jmwallet.backends.bitcoin_core import BitcoinCoreBackend

        _backend_instance = BitcoinCoreBackend(
            rpc_url=rpc_url,
            rpc_user=rpc_user,
            rpc_password=rpc_password,
        )
    elif backend_type == "neutrino":
        from jmwallet.backends.neutrino import NeutrinoBackend

        neutrino_url = getattr(settings.bitcoin, "neutrino_url", rpc_url)
        network = settings.network_config.network.value

        _backend_instance = NeutrinoBackend(
            neutrino_url=neutrino_url,
            network=network,
        )
    else:
        msg = f"Unknown backend type: {backend_type}"
        raise ValueError(msg)

    return _backend_instance


def reset_backend() -> None:
    """Reset the cached backend (for testing)."""
    global _backend_instance
    _backend_instance = None
