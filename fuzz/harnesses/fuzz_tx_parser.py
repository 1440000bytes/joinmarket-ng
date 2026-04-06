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

# Silence all loggers to ensure no signal-masking during fuzzing
from loguru import logger

logger.remove()
logging.disable(logging.CRITICAL)

with atheris.instrument_imports():
    from maker.tx_verification import parse_transaction
    from jmcore.models import NetworkType


def TestOneInput(data):
    """
    Fuzzer entry point with stable 1-to-1 mapping.
    1st byte: Network selection
    Rest: Transaction hex
    """
    if len(data) < 2:
        return

    try:
        # Use first byte to pick network stably
        networks = list(NetworkType)
        network = networks[data[0] % len(networks)]

        # Binary data to hex string for the parser
        tx_hex = data[1:].hex()

        # Critical target: the simplified transaction parser
        parse_transaction(tx_hex, network=network)

    except Exception:
        # We catch exceptions to prevent the fuzzer from stopping on
        # expected parsing errors. Internal unhandled crashes will
        # still trigger a fuzzer stop if they are not in this block
        # or if they cause a segfault/signal.
        pass


def main():
    # Only instrument after ensuring sys.path is correct
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
