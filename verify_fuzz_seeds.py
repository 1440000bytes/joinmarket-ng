# ruff: noqa: E402
import sys
import os

# Setup path
root_dir = os.path.dirname(os.path.abspath(__file__))
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

from maker.tx_verification import parse_transaction
from jmcore.models import NetworkType


def verify_seeds():
    corpus_dir = "fuzz/corpus/tx_parser"
    seeds = os.listdir(corpus_dir)
    for seed_name in seeds:
        with open(os.path.join(corpus_dir, seed_name), "rb") as f:
            data = f.read()

        # Mirror TestOneInput logic
        networks = list(NetworkType)
        network = networks[data[0] % len(networks)]
        tx_hex = data[1:].hex()

        result = parse_transaction(tx_hex, network=network)
        if result:
            print(
                f"[SUCCESS] Seed {seed_name} parsed successfully (Network: {network})"
            )
            print(
                f"   Inputs: {len(result['inputs'])}, Outputs: {len(result['outputs'])}"
            )
        else:
            print(f"[FAILED] Seed {seed_name} FAILED to parse")


if __name__ == "__main__":
    verify_seeds()
