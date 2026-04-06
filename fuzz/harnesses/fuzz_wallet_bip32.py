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
    from jmwallet.wallet.bip32 import HDKey


def TestOneInput(data):
    """Stable fuzzer for BIP32 key derivation."""
    if len(data) < 33:
        return

    try:
        # Use first byte to stabilize derivation path
        # 0 -> m/0, 1 -> m/44h/0h/0h/0/0, 2 -> arbitrary
        path_type = data[0] % 3
        if path_type == 0:
            path = "m/0"
        elif path_type == 1:
            path = "m/44'/0'/0'/0/0"
        else:
            try:
                path = data[1:32].decode("ascii")
            except UnicodeDecodeError:
                path = "m/0/0"

        # Use fixed 32 bytes for seed
        seed = data[0:32]

        # Derive
        hd_key = HDKey.from_seed(seed)
        hd_key.derive(path)

    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
