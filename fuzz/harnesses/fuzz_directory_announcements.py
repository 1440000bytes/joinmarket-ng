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
    from jmcore.models import MessageEnvelope
    from directory_server.handshake_handler import HandshakeHandler, HandshakeError


def TestOneInput(data):
    """Stable fuzzer for Directory Server announcements."""
    if len(data) < 2:
        return

    try:
        # Use first byte for logic selection
        choice = data[0] % 2

        if choice == 0:
            # Envelope parsing
            MessageEnvelope.from_bytes(data[1:])
        elif choice == 1:
            # Handshake handling
            handler = HandshakeHandler()
            try:
                handler.handle_handshake(data[1:])
            except HandshakeError:
                pass

    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
