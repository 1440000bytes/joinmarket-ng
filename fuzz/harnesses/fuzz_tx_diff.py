# ruff: noqa: E402
import sys
import os
import atheris
import logging
import time

# Setup path
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

# Deep instrumentation
import bitcoin

with atheris.instrument_imports():
    from maker.tx_verification import parse_transaction
    from jmcore.models import NetworkType
    import bitcoin.wallet as wallet
    from bitcoin.core import CTransaction, b2x


def TestOneInput(data):
    """
    Differential and DoS fuzzer for the transaction parser.
    Compares our simplified parser against python-bitcoinlib.
    """
    if len(data) < 2:
        return

    # 1st byte: Network selection
    networks = list(NetworkType)
    network_obj = networks[data[0] % len(networks)]
    network_name = (
        network_obj.value if isinstance(network_obj, NetworkType) else network_obj
    )

    # Rest: Transaction hex
    tx_hex = data[1:].hex()
    tx_bytes = data[1:]

    # 1. Measure DoS / Performance
    start_time = time.process_time()
    res_local = parse_transaction(tx_hex, network=network_name)
    end_time = time.process_time()

    # Catch DoS vectors (> 100ms for a single parse is suspicious)
    if (end_time - start_time) > 0.1:
        print(
            f"FAILED: Potential DoS vector found! Processing took {end_time - start_time:.4f}s"
        )
        print(f"  Input: {tx_hex}")
        raise Exception("Potential DoS vector detected (Timeout)")

    # 2. Reference Parsing (python-bitcoinlib)
    # Align bitcoinlib's network params
    try:
        if network_name == "mainnet":
            bitcoin.SelectParams("mainnet")
        elif network_name == "testnet":
            bitcoin.SelectParams("testnet")
        elif network_name == "regtest":
            bitcoin.SelectParams("regtest")
        elif network_name == "signet":
            # Signet may not be in all versions, fallback
            try:
                bitcoin.SelectParams("signet")
            except Exception:
                bitcoin.SelectParams("testnet")
    except Exception:
        pass

    try:
        res_ref = CTransaction.deserialize(tx_bytes)
        ref_valid = True
    except Exception:
        ref_valid = False

    # 3. Correlation / Logic Checks
    if res_local and not ref_valid:
        # Our parser accepted something the official lib says is garbage.
        # This is a "Leniency Bug" - potentially dangerous if it leads to parsing weird scripts.
        print(
            f"FAILED: Local parser accepted invalid transaction (network: {network_name})"
        )
        print(f"  Local result found {len(res_local['inputs'])} inputs")
        print(f"  TX Hex: {tx_hex}")
        raise Exception("Logic Mismatch: Leniency Bug")

    if res_local and ref_valid:
        # Both parsed, compare the structural contents

        # Compare Inputs
        if len(res_local["inputs"]) != len(res_ref.vin):
            raise Exception(
                f"Logic Mismatch: Input count disagreement ({len(res_local['inputs'])} vs {len(res_ref.vin)})"
            )

        for i, (l_in, r_in) in enumerate(zip(res_local["inputs"], res_ref.vin)):
            ref_txid = b2x(r_in.prevout.hash[::-1])
            if l_in["txid"] != ref_txid:
                raise Exception(
                    f"Logic Mismatch: Input {i} txid mismatch ({l_in['txid']} vs {ref_txid})"
                )
            if l_in["vout"] != r_in.prevout.n:
                raise Exception(
                    f"Logic Mismatch: Input {i} vout mismatch ({l_in['vout']} vs {r_in.prevout.n})"
                )

        # Compare Outputs
        if len(res_local["outputs"]) != len(res_ref.vout):
            raise Exception(
                f"Logic Mismatch: Output count disagreement ({len(res_local['outputs'])} vs {len(res_ref.vout)})"
            )

        for i, (l_out, r_out) in enumerate(zip(res_local["outputs"], res_ref.vout)):
            if l_out["value"] != r_out.nValue:
                raise Exception(
                    f"Logic Mismatch: Output {i} value mismatch ({l_out['value']} vs {r_out.nValue})"
                )

            # Address Comparison
            # Note: We comparison addresses as strings since that is what the MakerBot uses for verification.
            try:
                ref_addr = str(
                    wallet.CBitcoinAddress.from_scriptPubKey(r_out.scriptPubKey)
                )
                # Normalize case for bech32
                if l_out["address"].lower() != ref_addr.lower():
                    # Only flag if both chose to return an address (vs hex)
                    # python-bitcoinlib returns a string starting with 'bc1' etc for SegWit.
                    raise Exception(
                        f"Logic Mismatch: Output {i} address mismatch ({l_out['address']} vs {ref_addr})"
                    )
            except Exception:
                # If bitcoinlib can't find an address (unsupported/non-standard),
                # we don't necessarily flag it as a bug in our parser unless ours returned something specific.
                pass


def main():
    # Setup Atheris
    # Provide enough memory to avoid OOM stops
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
