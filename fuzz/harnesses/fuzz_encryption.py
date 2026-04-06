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
    from jmcore.encryption import decode_decrypt, create_encryption_box, init_pubkey


def TestOneInput(data):
    """Stable fuzzer for encryption utilities."""
    if len(data) < 32:
        return

    try:
        # Use first byte for logic selection
        choice = data[0] % 2

        if choice == 0:
            # Decode/Decrypt fuzzer
            decode_decrypt(data[1:], "fuzz_password")
        elif choice == 1:
            # Keypad/Public key handling
            try:
                init_pubkey(data[1:34].hex())
                create_encryption_box(data[1:33], b"noncenoncenoce")
            except (ValueError, TypeError):
                pass

    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
