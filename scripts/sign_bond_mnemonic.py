#!/usr/bin/env python3
"""Sign a fidelity bond spending PSBT using a BIP39 mnemonic seed phrase.

This script does not import from jmcore or jmwallet, so it works even when
pydantic or other project dependencies have version conflicts. Its external
dependencies are ``coincurve`` and ``mnemonic``.

This script is for users who have their bond wallet seed phrase (e.g., from
Sparrow) but do NOT have a hardware wallet. It derives the private key from
the mnemonic and derivation path, signs the bond spending transaction, and
outputs a fully signed raw transaction ready to broadcast.

SECURITY NOTES:
  - The mnemonic is read interactively (never as a CLI argument)
  - The mnemonic is never written to disk or logs
  - After signing, the key material is discarded

USAGE:
  python scripts/sign_bond_mnemonic.py <psbt_base64>
  python scripts/sign_bond_mnemonic.py --file psbt.txt

The PSBT must contain BIP32 derivation info (generated with --master-fingerprint
and --derivation-path in the spend-bond command). The script extracts the
derivation path from the PSBT automatically.

REQUIREMENTS:
  pip install coincurve mnemonic

BROADCAST:
  bitcoin-cli sendrawtransaction <signed_tx_hex>
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import struct
import sys
from pathlib import Path

from mnemonic import Mnemonic

# secp256k1 curve order -- used for BIP32 child key derivation
SECP256K1_N = int(
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16
)


# ---------------------------------------------------------------------------
# Bitcoin primitives (inline to avoid pydantic dependency)
# ---------------------------------------------------------------------------


def _hash256(data: bytes) -> bytes:
    """Double SHA-256 (Bitcoin's standard hash)."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a Bitcoin compact size varint. Returns (value, new_position)."""
    first = data[pos]
    if first < 0xFD:
        return first, pos + 1
    elif first == 0xFD:
        return struct.unpack("<H", data[pos + 1 : pos + 3])[0], pos + 3
    elif first == 0xFE:
        return struct.unpack("<I", data[pos + 1 : pos + 5])[0], pos + 5
    else:
        return struct.unpack("<Q", data[pos + 1 : pos + 9])[0], pos + 9


def _encode_varint(n: int) -> bytes:
    """Encode an integer as a Bitcoin compact size varint."""
    if n < 0xFD:
        return bytes([n])
    elif n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    else:
        return b"\xff" + struct.pack("<Q", n)


def _path_to_string(indices: list[int]) -> str:
    """Convert BIP32 uint32 indices to human-readable path string."""
    parts = ["m"]
    for idx in indices:
        if idx >= 0x80000000:
            parts.append(f"{idx - 0x80000000}'")
        else:
            parts.append(str(idx))
    return "/".join(parts)


# ---------------------------------------------------------------------------
# Minimal transaction parsing/serialization (no pydantic dataclasses)
# ---------------------------------------------------------------------------


class _TxInput:
    """Minimal transaction input representation."""

    __slots__ = ("txid_le", "vout", "scriptsig", "sequence")

    def __init__(
        self,
        txid_le: bytes,
        vout: int,
        scriptsig: bytes = b"",
        sequence: int = 0xFFFFFFFF,
    ) -> None:
        self.txid_le = txid_le
        self.vout = vout
        self.scriptsig = scriptsig
        self.sequence = sequence


class _TxOutput:
    """Minimal transaction output representation."""

    __slots__ = ("value", "script")

    def __init__(self, value: int, script: bytes) -> None:
        self.value = value
        self.script = script


class _ParsedTx:
    """Minimal parsed transaction."""

    __slots__ = ("version", "inputs", "outputs", "witnesses", "locktime")

    def __init__(
        self,
        version: int,
        inputs: list[_TxInput],
        outputs: list[_TxOutput],
        witnesses: list[list[bytes]],
        locktime: int,
    ) -> None:
        self.version = version
        self.inputs = inputs
        self.outputs = outputs
        self.witnesses = witnesses
        self.locktime = locktime


def _parse_tx(data: bytes) -> _ParsedTx:
    """Parse raw transaction bytes into a _ParsedTx."""
    pos = 0
    version = struct.unpack("<I", data[pos : pos + 4])[0]
    pos += 4

    # Check for segwit marker
    has_witness = False
    if data[pos] == 0x00 and data[pos + 1] != 0x00:
        has_witness = True
        pos += 2  # skip marker (0x00) and flag (0x01)

    # Inputs
    in_count, pos = _read_varint(data, pos)
    inputs: list[_TxInput] = []
    for _ in range(in_count):
        txid_le = data[pos : pos + 32]
        pos += 32
        vout = struct.unpack("<I", data[pos : pos + 4])[0]
        pos += 4
        ss_len, pos = _read_varint(data, pos)
        scriptsig = data[pos : pos + ss_len]
        pos += ss_len
        sequence = struct.unpack("<I", data[pos : pos + 4])[0]
        pos += 4
        inputs.append(_TxInput(txid_le, vout, scriptsig, sequence))

    # Outputs
    out_count, pos = _read_varint(data, pos)
    outputs: list[_TxOutput] = []
    for _ in range(out_count):
        value = struct.unpack("<Q", data[pos : pos + 8])[0]
        pos += 8
        sc_len, pos = _read_varint(data, pos)
        script = data[pos : pos + sc_len]
        pos += sc_len
        outputs.append(_TxOutput(value, script))

    # Witnesses
    witnesses: list[list[bytes]] = []
    if has_witness:
        for _ in range(in_count):
            stack_items, pos = _read_varint(data, pos)
            stack: list[bytes] = []
            for _ in range(stack_items):
                item_len, pos = _read_varint(data, pos)
                stack.append(data[pos : pos + item_len])
                pos += item_len
            witnesses.append(stack)

    locktime = struct.unpack("<I", data[pos : pos + 4])[0]
    return _ParsedTx(version, inputs, outputs, witnesses, locktime)


def _serialize_tx(
    version: int,
    inputs: list[_TxInput],
    outputs: list[_TxOutput],
    locktime: int,
    witnesses: list[list[bytes]] | None = None,
) -> bytes:
    """Serialize a transaction to raw bytes."""
    parts: list[bytes] = [struct.pack("<I", version)]

    if witnesses:
        parts.append(b"\x00\x01")  # segwit marker + flag

    # Inputs
    parts.append(_encode_varint(len(inputs)))
    for inp in inputs:
        parts.append(inp.txid_le)
        parts.append(struct.pack("<I", inp.vout))
        if inp.scriptsig:
            parts.append(_encode_varint(len(inp.scriptsig)))
            parts.append(inp.scriptsig)
        else:
            parts.append(b"\x00")
        parts.append(struct.pack("<I", inp.sequence))

    # Outputs
    parts.append(_encode_varint(len(outputs)))
    for out in outputs:
        parts.append(struct.pack("<Q", out.value))
        parts.append(_encode_varint(len(out.script)))
        parts.append(out.script)

    # Witnesses
    if witnesses:
        for stack in witnesses:
            parts.append(_encode_varint(len(stack)))
            for item in stack:
                parts.append(_encode_varint(len(item)))
                parts.append(item)

    parts.append(struct.pack("<I", locktime))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# BIP143 sighash (segwit)
# ---------------------------------------------------------------------------


def _compute_sighash_segwit(
    tx: _ParsedTx,
    input_index: int,
    script_code: bytes,
    value: int,
    sighash_type: int = 1,
) -> bytes:
    """Compute BIP143 sighash for a segwit input.

    For P2WSH spending, script_code is the witness script.
    """
    # hashPrevouts
    prevouts = b"".join(inp.txid_le + struct.pack("<I", inp.vout) for inp in tx.inputs)
    hash_prevouts = _hash256(prevouts)

    # hashSequence
    sequences = b"".join(struct.pack("<I", inp.sequence) for inp in tx.inputs)
    hash_sequence = _hash256(sequences)

    # hashOutputs
    outputs_data = b"".join(
        struct.pack("<Q", out.value) + _encode_varint(len(out.script)) + out.script
        for out in tx.outputs
    )
    hash_outputs = _hash256(outputs_data)

    # The input being signed
    inp = tx.inputs[input_index]

    preimage = (
        struct.pack("<I", tx.version)  # nVersion
        + hash_prevouts  # hashPrevouts
        + hash_sequence  # hashSequence
        + inp.txid_le  # outpoint txid
        + struct.pack("<I", inp.vout)  # outpoint index
        + _encode_varint(len(script_code))  # scriptCode length
        + script_code  # scriptCode
        + struct.pack("<Q", value)  # value
        + struct.pack("<I", inp.sequence)  # nSequence
        + hash_outputs  # hashOutputs
        + struct.pack("<I", tx.locktime)  # nLocktime
        + struct.pack("<I", sighash_type)  # sighash type
    )

    return _hash256(preimage)


# ---------------------------------------------------------------------------
# PSBT parser
# ---------------------------------------------------------------------------


def parse_psbt(psbt_b64: str) -> dict:
    """Parse a PSBT and extract the fields needed for signing.

    Implements a minimal BIP-174 PSBT parser that extracts only the fields
    we need: the unsigned transaction, witness UTXO, witness script, and
    BIP32 derivation info.

    Returns:
        Dict with keys:
          - unsigned_tx_bytes: Raw unsigned transaction bytes
          - witness_utxo_value: UTXO value in satoshis
          - witness_utxo_script: UTXO scriptPubKey bytes
          - witness_script: The P2WSH witness script bytes
          - bip32_pubkey: Public key from BIP32 derivation (33 bytes)
          - bip32_fingerprint: Master fingerprint (4 bytes)
          - bip32_path: Derivation path as list of uint32 indices
          - bip32_path_str: Human-readable derivation path string
    """
    raw = base64.b64decode(psbt_b64)

    # Verify magic
    if raw[:5] != b"psbt\xff":
        raise ValueError("Invalid PSBT: missing magic bytes")

    pos = 5
    result: dict = {}

    # --- Parse global map ---
    while pos < len(raw):
        if raw[pos] == 0x00:  # Separator
            pos += 1
            break

        # Read key
        key_len, pos = _read_varint(raw, pos)
        key = raw[pos : pos + key_len]
        pos += key_len

        # Read value
        val_len, pos = _read_varint(raw, pos)
        value = raw[pos : pos + val_len]
        pos += val_len

        key_type = key[0]
        if key_type == 0x00:  # PSBT_GLOBAL_UNSIGNED_TX
            result["unsigned_tx_bytes"] = value

    # --- Parse per-input maps (we only handle one input) ---
    while pos < len(raw):
        if raw[pos] == 0x00:  # Separator (end of input map)
            pos += 1
            break

        # Read key
        key_len, pos = _read_varint(raw, pos)
        key = raw[pos : pos + key_len]
        pos += key_len

        # Read value
        val_len, pos = _read_varint(raw, pos)
        value = raw[pos : pos + val_len]
        pos += val_len

        key_type = key[0]

        if key_type == 0x01:  # PSBT_IN_WITNESS_UTXO
            utxo_value = struct.unpack("<Q", value[:8])[0]
            script_len, spos = _read_varint(value, 8)
            utxo_script = value[spos : spos + script_len]
            result["witness_utxo_value"] = utxo_value
            result["witness_utxo_script"] = utxo_script

        elif key_type == 0x05:  # PSBT_IN_WITNESS_SCRIPT
            result["witness_script"] = value

        elif key_type == 0x06:  # PSBT_IN_BIP32_DERIVATION
            # Key = 0x06 + <33-byte pubkey>
            pubkey = key[1:]  # Skip key type byte
            # Value = <4-byte fingerprint> + <4-byte LE index>...
            fingerprint = value[:4]
            path_indices = []
            for i in range(4, len(value), 4):
                idx = struct.unpack("<I", value[i : i + 4])[0]
                path_indices.append(idx)
            result["bip32_pubkey"] = pubkey
            result["bip32_fingerprint"] = fingerprint
            result["bip32_path"] = path_indices
            result["bip32_path_str"] = _path_to_string(path_indices)

    # Validate we got everything we need
    required = ["unsigned_tx_bytes", "witness_script", "witness_utxo_value"]
    for field in required:
        if field not in result:
            raise ValueError(f"PSBT missing required field: {field}")

    return result


# ---------------------------------------------------------------------------
# BIP32 key derivation (inline to avoid pydantic dependency via jmwallet)
# ---------------------------------------------------------------------------


def _parse_derivation_path(path: str) -> list[int]:
    """Parse a BIP32 derivation path string into uint32 indices.

    Accepts: m/84'/0'/0'/0/0 or m/84h/0h/0h/0/0
    """
    parts = path.strip().split("/")
    if parts[0] != "m":
        raise ValueError(f"Path must start with 'm': {path}")

    indices: list[int] = []
    for part in parts[1:]:
        hardened = part.endswith("'") or part.endswith("h")
        idx = int(part.rstrip("'h"))
        if hardened:
            idx += 0x80000000
        indices.append(idx)
    return indices


def derive_key_from_mnemonic(
    mnemonic: str,
    path: str | list[int],
    passphrase: str = "",
) -> tuple[bytes, bytes]:
    """Derive a private key and public key from a BIP39 mnemonic and path.

    Uses standalone BIP39 validation and BIP32 key derivation without project
    imports. Depends on ``coincurve`` and ``mnemonic``.

    Args:
        mnemonic: BIP39 mnemonic phrase (12 or 24 words).
        path: Derivation path as string ("m/84'/0'/0'/0/0") or list of uint32.
        passphrase: Optional BIP39 passphrase.

    Returns:
        Tuple of (private_key_bytes, compressed_public_key_bytes).
    """
    from coincurve import PrivateKey

    normalized_mnemonic = " ".join(mnemonic.strip().split())
    bip39 = Mnemonic("english")
    if not bip39.check(normalized_mnemonic):
        raise ValueError("Invalid English BIP39 mnemonic or checksum")
    seed = bip39.to_seed(normalized_mnemonic, passphrase=passphrase)

    # BIP32: seed -> master key
    master_hmac = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    master_key_bytes = master_hmac[:32]
    master_chain_code = master_hmac[32:]
    master_key_int = int.from_bytes(master_key_bytes, "big")
    if not 1 <= master_key_int < SECP256K1_N:
        raise ValueError("BIP32 produced an invalid master private key")

    # Derive child keys along the path
    if isinstance(path, list):
        indices = path
    else:
        indices = _parse_derivation_path(path)

    key_bytes = master_key_bytes
    chain_code = master_chain_code

    for index in indices:
        hardened = index >= 0x80000000
        if hardened:
            # Hardened: HMAC-SHA512(chain_code, 0x00 + key + index)
            data = b"\x00" + key_bytes + struct.pack(">I", index)
        else:
            # Normal: HMAC-SHA512(chain_code, compressed_pubkey + index)
            pubkey = PrivateKey(key_bytes).public_key.format(compressed=True)
            data = pubkey + struct.pack(">I", index)

        child_hmac = hmac.new(chain_code, data, hashlib.sha512).digest()
        child_key_offset = int.from_bytes(child_hmac[:32], "big")
        if child_key_offset >= SECP256K1_N:
            raise ValueError(f"BIP32 produced an invalid child offset at index {index}")
        parent_key_int = int.from_bytes(key_bytes, "big")
        child_key_int = (parent_key_int + child_key_offset) % SECP256K1_N
        if child_key_int == 0:
            raise ValueError(
                f"BIP32 produced an invalid zero child key at index {index}"
            )

        key_bytes = child_key_int.to_bytes(32, "big")
        chain_code = child_hmac[32:]

    privkey = PrivateKey(key_bytes)
    pubkey = privkey.public_key.format(compressed=True)
    return key_bytes, pubkey


# ---------------------------------------------------------------------------
# Transaction signing
# ---------------------------------------------------------------------------


def sign_bond_transaction(
    unsigned_tx_bytes: bytes,
    witness_script: bytes,
    utxo_value: int,
    private_key_bytes: bytes,
) -> str:
    """Sign the bond spending transaction and return the signed tx hex.

    Args:
        unsigned_tx_bytes: The raw unsigned transaction from the PSBT.
        witness_script: The P2WSH witness script (CLTV timelock script).
        utxo_value: The UTXO value in satoshis.
        private_key_bytes: The 32-byte private key.

    Returns:
        Hex string of the fully signed transaction, ready to broadcast.
    """
    from coincurve import PrivateKey

    # Parse the unsigned transaction
    tx = _parse_tx(unsigned_tx_bytes)

    # Compute the BIP143 segwit sighash
    sighash_type = 1  # SIGHASH_ALL
    sighash = _compute_sighash_segwit(
        tx=tx,
        input_index=0,
        script_code=witness_script,
        value=utxo_value,
        sighash_type=sighash_type,
    )

    # Sign with the private key (DER-encoded + sighash byte)
    privkey = PrivateKey(private_key_bytes)
    signature = privkey.sign(sighash, hasher=None) + bytes([sighash_type])

    # Witness stack for P2WSH: [signature, witness_script]
    witness_stack = [signature, witness_script]

    # Serialize the fully signed transaction with witness data
    signed_tx = _serialize_tx(
        version=tx.version,
        inputs=tx.inputs,
        outputs=tx.outputs,
        locktime=tx.locktime,
        witnesses=[witness_stack],
    )

    return signed_tx.hex()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sign a fidelity bond spending PSBT with a BIP39 mnemonic.",
        epilog=(
            "The mnemonic is read interactively (never as a CLI argument). "
            "After signing, the signed raw transaction hex is printed to stdout. "
            "Broadcast with: bitcoin-cli sendrawtransaction <hex>"
        ),
    )
    parser.add_argument(
        "psbt",
        nargs="?",
        help="Base64-encoded PSBT string",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Read PSBT from file instead of argument",
    )
    parser.add_argument(
        "--derivation-path",
        help=(
            "Override the BIP32 derivation path "
            "(default: extracted from PSBT's BIP32 derivation field)"
        ),
    )
    parser.add_argument(
        "--passphrase",
        action="store_true",
        help="Prompt for a BIP39 passphrase (default: no passphrase)",
    )
    args = parser.parse_args()

    # Read PSBT
    if args.file:
        psbt_b64 = args.file.read_text().strip()
    elif args.psbt:
        psbt_b64 = args.psbt.strip()
    else:
        parser.error("Provide a PSBT as an argument or via --file")

    # Parse PSBT
    print("Parsing PSBT...", file=sys.stderr)
    try:
        psbt_data = parse_psbt(psbt_b64)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine derivation path
    if args.derivation_path:
        deriv_path = args.derivation_path
        print(f"Using provided derivation path: {deriv_path}", file=sys.stderr)
    elif "bip32_path" in psbt_data:
        deriv_path = psbt_data["bip32_path_str"]
        fingerprint_hex = psbt_data["bip32_fingerprint"].hex()
        print(
            f"Found BIP32 derivation in PSBT: {deriv_path} "
            f"(fingerprint: {fingerprint_hex})",
            file=sys.stderr,
        )
    else:
        print(
            "ERROR: No BIP32 derivation path found in the PSBT.\n"
            "  Either:\n"
            "  - Re-generate the PSBT with --master-fingerprint and --derivation-path\n"
            "  - Or provide --derivation-path to this script",
            file=sys.stderr,
        )
        sys.exit(1)

    # Show transaction details
    witness_script = psbt_data["witness_script"]
    utxo_value = psbt_data["witness_utxo_value"]
    print(f"Witness script: {witness_script.hex()}", file=sys.stderr)
    print(f"UTXO value: {utxo_value} sats", file=sys.stderr)

    # Read mnemonic securely
    print(file=sys.stderr)
    print("Enter your BIP39 mnemonic (12 or 24 words):", file=sys.stderr)
    print("(input is hidden)", file=sys.stderr)
    mnemonic = getpass.getpass(prompt="> ")

    if not mnemonic.strip():
        print("ERROR: Empty mnemonic", file=sys.stderr)
        sys.exit(1)

    # Reject malformed mnemonics before accepting an optional passphrase.
    words = mnemonic.strip().split()
    if len(words) not in (12, 15, 18, 21, 24):
        print(
            f"ERROR: Expected 12-24 words, got {len(words)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not Mnemonic("english").check(" ".join(words)):
        print("ERROR: Invalid English BIP39 mnemonic or checksum", file=sys.stderr)
        sys.exit(1)

    # Optional passphrase
    passphrase = ""
    if args.passphrase:
        passphrase = getpass.getpass(prompt="BIP39 passphrase: ")

    # Derive key
    print(f"\nDeriving key from path {deriv_path}...", file=sys.stderr)
    try:
        privkey_bytes, pubkey_bytes = derive_key_from_mnemonic(
            mnemonic.strip(), deriv_path, passphrase
        )
    except Exception as e:
        print(f"ERROR: Key derivation failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Clear mnemonic from memory (best-effort in Python)
    mnemonic = "x" * len(mnemonic)  # noqa: F841
    del mnemonic

    # Verify pubkey matches
    if "bip32_pubkey" in psbt_data:
        expected_pubkey = psbt_data["bip32_pubkey"]
        if pubkey_bytes != expected_pubkey:
            print(
                f"ERROR: Derived pubkey does not match PSBT!\n"
                f"  Derived:  {pubkey_bytes.hex()}\n"
                f"  Expected: {expected_pubkey.hex()}\n"
                f"  Check: mnemonic, passphrase, and derivation path",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Pubkey verified: matches PSBT", file=sys.stderr)
    else:
        print(
            f"WARNING: Cannot verify pubkey (no BIP32 derivation in PSBT)\n"
            f"  Derived pubkey: {pubkey_bytes.hex()}",
            file=sys.stderr,
        )

    # Sign
    print("Signing transaction...", file=sys.stderr)
    try:
        signed_tx_hex = sign_bond_transaction(
            unsigned_tx_bytes=psbt_data["unsigned_tx_bytes"],
            witness_script=witness_script,
            utxo_value=utxo_value,
            private_key_bytes=privkey_bytes,
        )
    except Exception as e:
        print(f"ERROR: Signing failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clear key material
        privkey_bytes = b"\x00" * 32  # noqa: F841
        del privkey_bytes

    # Output the signed transaction
    print("\n" + "=" * 80, file=sys.stderr)
    print("SIGNED TRANSACTION (raw hex):", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(signed_tx_hex)  # stdout -- can be piped
    print("=" * 80, file=sys.stderr)
    print(file=sys.stderr)
    print("Broadcast with:", file=sys.stderr)
    print(f"  bitcoin-cli sendrawtransaction {signed_tx_hex}", file=sys.stderr)
    print(file=sys.stderr)
    print("VERIFY FIRST: bitcoin-cli decoderawtransaction <hex>", file=sys.stderr)


if __name__ == "__main__":
    main()
