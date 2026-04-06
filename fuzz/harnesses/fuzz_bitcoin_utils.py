# ruff: noqa: E402
import sys
import os
import atheris
import logging

# Setup path to include all component source directories
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
components = [
    "jmcore",
    "jmwallet",
    "jmwalletd",
    "maker",
    "taker",
    "directory_server",
    "orderbook_watcher",
]
for component in components:
    sys.path.append(os.path.join(root_dir, component, "src"))

# Silence loggers
from loguru import logger

logger.remove()
logging.disable(logging.CRITICAL)

with atheris.instrument_imports():
    from jmcore.bitcoin import (
        decode_varint,
        address_to_scriptpubkey,
        scriptpubkey_to_address,
        NetworkType,
    )


def TestOneInput(data):
    """Stable fuzzer for Bitcoin utilities."""
    if len(data) < 2:
        return

    try:
        # Use first byte to pick target stably
        target = data[0] % 3

        if target == 0:
            # Varint decoding
            decode_varint(data[1:], 0)
        elif target == 1:
            # Address to ScriptPubKey
            # Use text input for address
            try:
                addr = data[1:].decode("ascii")
                network = list(NetworkType)[data[0] % len(NetworkType)]
                address_to_scriptpubkey(addr, network)
            except (UnicodeDecodeError, ValueError):
                pass
        elif target == 2:
            # ScriptPubKey to Address
            network = list(NetworkType)[data[0] % len(NetworkType)]
            scriptpubkey_to_address(data[1:], network)

    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
