# ruff: noqa: E402
import sys
import os
import atheris
import logging
from unittest.mock import MagicMock

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
    from jmwallet.wallet.service import WalletService
    from jmwallet.wallet.models import UTXOInfo
    from jmwallet.backends.base import BlockchainBackend


def TestOneInput(data):
    """Deep logic fuzzer for WalletService."""
    fdp = atheris.FuzzedDataProvider(data)

    # Stable mnemonic for now, maybe fuzz later
    mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

    # Mock backend
    mock_backend = MagicMock(spec=BlockchainBackend)

    try:
        # Initialize service
        ws = WalletService(
            mnemonic=mnemonic, backend=mock_backend, network="regtest", mixdepth_count=5
        )

        # Fuzz UTXO cache population
        num_utxos = fdp.ConsumeIntInRange(0, 50)
        for _ in range(num_utxos):
            mixdepth = fdp.ConsumeIntInRange(0, 4)
            if mixdepth not in ws.utxo_cache:
                ws.utxo_cache[mixdepth] = []

            utxo = UTXOInfo(
                txid=fdp.ConsumeBytes(32).hex(),
                vout=fdp.ConsumeIntInRange(0, 100),
                value=fdp.ConsumeIntInRange(0, 2100000000000000),
                address=f"bcrt1q{fdp.ConsumeBytes(20).hex()}",
                confirmations=fdp.ConsumeIntInRange(0, 1000),
                frozen=fdp.ConsumeBool(),
                is_fidelity_bond=fdp.ConsumeBool(),
                label=fdp.ConsumeUnicodeNoSurrogates(20) if fdp.ConsumeBool() else None,
            )
            ws.utxo_cache[mixdepth].append(utxo)

        # Target: select_utxos
        target_md = fdp.ConsumeIntInRange(0, 4)
        target_amount = fdp.ConsumeIntInRange(0, 2100000000000000)
        min_conf = fdp.ConsumeIntInRange(0, 100)

        try:
            ws.select_utxos(
                mixdepth=target_md,
                target_amount=target_amount,
                min_confirmations=min_conf,
                include_fidelity_bonds=fdp.ConsumeBool(),
            )
        except ValueError:
            pass  # Expected if insufficient funds

        # Target: select_utxos_with_merge
        merge_algos = ["default", "gradual", "greedy", "random", "unknown"]
        algo = fdp.PickValueInList(merge_algos)

        try:
            ws.select_utxos_with_merge(
                mixdepth=target_md,
                target_amount=target_amount,
                min_confirmations=min_conf,
                merge_algorithm=algo,
                include_fidelity_bonds=fdp.ConsumeBool(),
            )
        except ValueError:
            pass

        # Target: address generation
        ws.get_address(
            mixdepth=fdp.ConsumeIntInRange(0, 10),  # Test out of bounds
            change=fdp.ConsumeIntInRange(0, 1),
            index=fdp.ConsumeIntInRange(0, 1000000),
        )

    except (ValueError, TypeError, KeyError):
        pass
    except Exception:
        # Unexpected exceptions should be surfaced
        raise


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
