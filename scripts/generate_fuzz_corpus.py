# ruff: noqa: E402
#!/usr/bin/env python3
"""
Generate a seed corpus for JoinMarket-NG fuzz testing.
Updated for 1-to-1 stable mapping harnesses.
"""

import os
import json


def generate_tx_parser_corpus(base_dir):
    """Generate binary seeds: 1st byte network index + raw tx bytes."""
    corpus_dir = os.path.join(base_dir, "corpus/tx_parser")
    os.makedirs(corpus_dir, exist_ok=True)

    # 0 = Mainnet, 1 = Testnet, 2 = Regtest, 3 = Signet
    # tx_segwit
    tx_segwit_raw = bytes.fromhex(
        "010000000001010000000000000000000000000000000000000000000000000000000000000000ffffffff0140420f0000000000160014751e76e0a152d5b6100500a89d7b4c48398a6f3b00000000"
    )
    # tx_legacy
    tx_legacy_raw = bytes.fromhex(
        "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff0140420f00000000001976a914751e76e0a152d5b6100500a89d7b4c48398a6f3b88ac00000000"
    )

    # Mainnet Segwit
    with open(os.path.join(corpus_dir, "mainnet_segwit.bin"), "wb") as f:
        f.write(bytes([0]) + tx_segwit_raw)

    # Testnet Legacy
    with open(os.path.join(corpus_dir, "testnet_legacy.bin"), "wb") as f:
        f.write(bytes([1]) + tx_legacy_raw)


def generate_bitcoin_utils_corpus(base_dir):
    """Generate binary seeds for utils."""
    corpus_dir = os.path.join(base_dir, "corpus/bitcoin_utils")
    os.makedirs(corpus_dir, exist_ok=True)

    # Target 0: Varint
    with open(os.path.join(corpus_dir, "varint_255.bin"), "wb") as f:
        f.write(bytes([0]) + b"\xfd\xff\x00")  # Target 0 (Varint), Value 255

    # Target 2: ScriptPubKey to Address (Mainnet P2WPKH)
    spk = bytes.fromhex("0014751e76e0a152d5b6100500a89d7b4c48398a6f3b")
    with open(os.path.join(corpus_dir, "spk_p2wpkh.bin"), "wb") as f:
        f.write(bytes([2]) + spk)  # Target 2, Mainnet (0 % len(NetworkType))


def generate_wallet_api_corpus(base_dir):
    """Generate binary seeds: 1st byte model index + JSON string."""
    corpus_dir = os.path.join(base_dir, "corpus/wallet_api")
    os.makedirs(corpus_dir, exist_ok=True)

    # Model 0: CreateWalletRequest
    data = {"walletname": "fuzz", "password": "pass", "wallettype": "sw-fb"}
    with open(os.path.join(corpus_dir, "create_wallet.bin"), "wb") as f:
        f.write(bytes([0]) + json.dumps(data).encode("utf-8"))


if __name__ == "__main__":
    base_fuzz_dir = "fuzz"
    print(f"Generating revised seed corpus in {base_fuzz_dir}/corpus/...")
    generate_tx_parser_corpus(base_fuzz_dir)
    generate_bitcoin_utils_corpus(base_fuzz_dir)
    generate_wallet_api_corpus(base_fuzz_dir)
    print("Done.")
