# ruff: noqa: E402
import sys
import os
import json
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
    from jmwalletd.models import (
        CreateWalletRequest,
        RecoverWalletRequest,
        UnlockWalletRequest,
        DirectSendRequest,
        DoCoinjoinRequest,
        RunScheduleRequest,
        StartMakerRequest,
    )
    from pydantic import ValidationError


def TestOneInput(data):
    """Deep fuzzer for Wallet API models with structured data."""
    if len(data) < 2:
        return

    fdp = atheris.FuzzedDataProvider(data)

    try:
        # Request models to target
        classes = [
            CreateWalletRequest,
            RecoverWalletRequest,
            UnlockWalletRequest,
            DirectSendRequest,
            DoCoinjoinRequest,
            RunScheduleRequest,
            StartMakerRequest,
        ]
        target_class = fdp.PickValueInList(classes)

        # Build fuzzed dict based on target model
        payload = {}
        if target_class == CreateWalletRequest:
            payload = {
                "walletname": fdp.ConsumeUnicodeNoSurrogates(32),
                "password": fdp.ConsumeUnicodeNoSurrogates(64),
                "wallettype": fdp.PickValueInList(
                    ["sw-fb", fdp.ConsumeUnicodeNoSurrogates(10)]
                ),
            }
        elif target_class == RecoverWalletRequest:
            payload = {
                "walletname": fdp.ConsumeUnicodeNoSurrogates(32),
                "password": fdp.ConsumeUnicodeNoSurrogates(64),
                "seedphrase": fdp.ConsumeUnicodeNoSurrogates(128),
                "wallettype": fdp.PickValueInList(
                    ["sw-fb", fdp.ConsumeUnicodeNoSurrogates(10)]
                ),
            }
        elif target_class == UnlockWalletRequest:
            payload = {"password": fdp.ConsumeUnicodeNoSurrogates(64)}
        elif target_class == DirectSendRequest:
            payload = {
                "mixdepth": fdp.ConsumeIntInRange(0, 10),
                "amount": fdp.ConsumeIntInRange(0, 2100000000000000),
                "address": fdp.ConsumeUnicodeNoSurrogates(64),
                "password": fdp.ConsumeUnicodeNoSurrogates(64),
            }
        else:
            # Generic fallback for others
            try:
                payload = json.loads(fdp.ConsumeUnicodeNoSurrogates(256))
            except json.JSONDecodeError:
                return

        # Validate
        try:
            target_class.model_validate(payload)
        except ValidationError:
            pass

    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
