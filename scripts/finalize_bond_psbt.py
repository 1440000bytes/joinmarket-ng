#!/usr/bin/env python3
"""Finalize a signed fidelity bond spending PSBT.

This script is for hardware-wallet flows where the device returns a signed
PSBT containing a partial signature, but Bitcoin Core's ``finalizepsbt`` does
not finalize the custom CLTV P2WSH witness script.

It cryptographically verifies the partial signature (BIP143 SIGHASH_ALL over
the CLTV witness script), builds the final witness stack for the single-input,
single-output bond sweep:

    [signature, witness_script]

and outputs the final raw transaction hex ready for inspection and broadcast.
Because the signature is verified, a successful run proves the signing device
produced a valid bond spend signature. This makes the script suitable as the
verification step of the hardware wallet compatibility test described in
docs/fidelity-bond-operations.md (which uses a synthetic, non-broadcastable UTXO).

The script is intentionally dependency-free (Python standard library only) so
it can run on an offline machine. Signature verification only handles public
data, so the pure-Python secp256k1 arithmetic below is not a side-channel
concern.

Usage:
  python scripts/finalize_bond_psbt.py <signed_psbt_base64>
  python scripts/finalize_bond_psbt.py --file signed-bond.psbt

Broadcast:
  bitcoin-cli testmempoolaccept '["<signed_tx_hex>"]'
  bitcoin-cli sendrawtransaction "<signed_tx_hex>"
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# secp256k1 curve parameters (used for signature verification only)
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_SECP256K1_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a Bitcoin compact size integer."""
    if pos >= len(data):
        raise ValueError("Unexpected end of data while reading compact size")

    first = data[pos]
    if first < 0xFD:
        return first, pos + 1
    if first == 0xFD:
        if pos + 3 > len(data):
            raise ValueError("Truncated compact size uint16")
        return struct.unpack("<H", data[pos + 1 : pos + 3])[0], pos + 3
    if first == 0xFE:
        if pos + 5 > len(data):
            raise ValueError("Truncated compact size uint32")
        return struct.unpack("<I", data[pos + 1 : pos + 5])[0], pos + 5
    if pos + 9 > len(data):
        raise ValueError("Truncated compact size uint64")
    return struct.unpack("<Q", data[pos + 1 : pos + 9])[0], pos + 9


def _encode_varint(n: int) -> bytes:
    """Encode a Bitcoin compact size integer."""
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def _read_psbt_pair(data: bytes, pos: int) -> tuple[bytes | None, bytes | None, int]:
    """Read one PSBT key-value pair. Empty key means map separator."""
    key_len, pos = _read_varint(data, pos)
    if key_len == 0:
        return None, None, pos
    if pos + key_len > len(data):
        raise ValueError("Truncated PSBT key")

    key = data[pos : pos + key_len]
    pos += key_len

    value_len, pos = _read_varint(data, pos)
    if pos + value_len > len(data):
        raise ValueError("Truncated PSBT value")
    value = data[pos : pos + value_len]
    pos += value_len

    return key, value, pos


@dataclass
class _UnsignedTxFields:
    """Fields of the single-input, single-output unsigned bond transaction."""

    version: bytes  # 4-byte LE
    outpoint: bytes  # 36 bytes (txid LE + vout LE)
    sequence: bytes  # 4-byte LE
    outputs: bytes  # serialized output(s) without the count varint
    locktime: bytes  # 4-byte LE


def _parse_unsigned_tx(unsigned_tx: bytes) -> _UnsignedTxFields:
    """Validate and split the unsigned transaction shape supported here."""
    if len(unsigned_tx) < 10:
        raise ValueError("Unsigned transaction is too short")

    pos = 4
    if unsigned_tx[pos] == 0x00 and unsigned_tx[pos + 1] != 0x00:
        raise ValueError("PSBT unsigned transaction unexpectedly contains witness data")

    input_count, pos = _read_varint(unsigned_tx, pos)
    if input_count != 1:
        raise ValueError(f"Expected exactly 1 input, got {input_count}")

    if pos + 36 > len(unsigned_tx):
        raise ValueError("Unsigned transaction input outpoint is truncated")
    outpoint = unsigned_tx[pos : pos + 36]
    pos += 36

    script_len, pos = _read_varint(unsigned_tx, pos)
    if pos + script_len + 4 > len(unsigned_tx):
        raise ValueError("Unsigned transaction input script or sequence is truncated")
    pos += script_len
    sequence = unsigned_tx[pos : pos + 4]
    pos += 4

    output_count, pos = _read_varint(unsigned_tx, pos)
    if output_count != 1:
        raise ValueError(f"Expected exactly 1 output, got {output_count}")

    outputs_start = pos
    if pos + 8 > len(unsigned_tx):
        raise ValueError("Unsigned transaction output value is truncated")
    pos += 8

    output_script_len, pos = _read_varint(unsigned_tx, pos)
    if pos + output_script_len > len(unsigned_tx):
        raise ValueError("Unsigned transaction output script is truncated")
    pos += output_script_len

    if pos != len(unsigned_tx) - 4:
        raise ValueError("Unsigned transaction has trailing data before locktime")

    return _UnsignedTxFields(
        version=unsigned_tx[:4],
        outpoint=outpoint,
        sequence=sequence,
        outputs=unsigned_tx[outputs_start:pos],
        locktime=unsigned_tx[pos:],
    )


def _validate_p2wsh_script(witness_utxo_script: bytes, witness_script: bytes) -> None:
    """Verify witness_utxo is OP_0 SHA256(witness_script)."""
    expected = b"\x00\x20" + hashlib.sha256(witness_script).digest()
    if witness_utxo_script != expected:
        raise ValueError(
            "witness_script does not match the P2WSH witness_utxo scriptPubKey"
        )


def _extract_freeze_script_pubkey(witness_script: bytes) -> bytes:
    """Extract the pubkey from <locktime> OP_CLTV OP_DROP <pubkey> OP_CHECKSIG."""
    pos = 0
    if pos >= len(witness_script):
        raise ValueError("witness_script is empty")

    locktime_len = witness_script[pos]
    pos += 1
    if locktime_len < 1 or locktime_len > 5:
        raise ValueError("witness_script has invalid locktime push")
    if pos + locktime_len + 2 > len(witness_script):
        raise ValueError("witness_script locktime push is truncated")
    pos += locktime_len

    if pos >= len(witness_script):
        raise ValueError("witness_script missing OP_CHECKLOCKTIMEVERIFY")
    if witness_script[pos] != 0xB1:
        raise ValueError("witness_script missing OP_CHECKLOCKTIMEVERIFY")
    pos += 1

    if pos >= len(witness_script):
        raise ValueError("witness_script missing OP_DROP")
    if witness_script[pos] != 0x75:
        raise ValueError("witness_script missing OP_DROP")
    pos += 1

    if pos >= len(witness_script):
        raise ValueError("witness_script missing pubkey push")
    pubkey_len = witness_script[pos]
    pos += 1
    if pubkey_len != 33:
        raise ValueError("witness_script pubkey must be compressed")
    if pos + pubkey_len > len(witness_script):
        raise ValueError("witness_script pubkey is truncated")
    if pos + pubkey_len + 1 != len(witness_script):
        raise ValueError("witness_script has unexpected trailing data")

    pubkey = witness_script[pos : pos + pubkey_len]
    pos += pubkey_len
    if witness_script[pos] != 0xAC:
        raise ValueError("witness_script missing OP_CHECKSIG")

    return pubkey


def _extract_witness_utxo_script(witness_utxo: bytes) -> bytes:
    """Extract scriptPubKey from a serialized PSBT witness_utxo value."""
    if len(witness_utxo) < 9:
        raise ValueError("witness_utxo is too short")
    script_len, pos = _read_varint(witness_utxo, 8)
    script = witness_utxo[pos : pos + script_len]
    if len(script) != script_len:
        raise ValueError("witness_utxo scriptPubKey is truncated")
    return script


def _hash256(data: bytes) -> bytes:
    """Double SHA-256."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _compute_bip143_sighash(
    tx: _UnsignedTxFields, witness_script: bytes, utxo_value: int
) -> bytes:
    """Compute the BIP143 SIGHASH_ALL digest for the single P2WSH input."""
    script_code = _encode_varint(len(witness_script)) + witness_script
    preimage = (
        tx.version
        + _hash256(tx.outpoint)  # hashPrevouts
        + _hash256(tx.sequence)  # hashSequence
        + tx.outpoint
        + script_code
        + struct.pack("<Q", utxo_value)
        + tx.sequence
        + _hash256(tx.outputs)  # hashOutputs
        + tx.locktime
        + struct.pack("<I", 1)  # SIGHASH_ALL
    )
    return _hash256(preimage)


def _parse_der_signature(der: bytes) -> tuple[int, int]:
    """Parse a strictly BIP66-encoded ECDSA signature into (r, s)."""
    if not 8 <= len(der) <= 72 or der[0] != 0x30:
        raise ValueError("Signature is not DER encoded")
    if der[1] != len(der) - 2:
        raise ValueError("Signature has an invalid DER length")

    pos = 2
    if der[pos] != 0x02:
        raise ValueError("Signature DER r marker missing")
    r_len = der[pos + 1]
    pos += 2
    if r_len == 0:
        raise ValueError("Signature DER r value is empty")
    if pos + r_len > len(der):
        raise ValueError("Signature DER r value is truncated")
    r_bytes = der[pos : pos + r_len]
    if r_bytes[0] & 0x80:
        raise ValueError("Signature DER r value is negative")
    if r_len > 1 and r_bytes[0] == 0 and not r_bytes[1] & 0x80:
        raise ValueError("Signature DER r value has an unnecessary leading zero")
    r = int.from_bytes(r_bytes, "big")
    pos += r_len

    if pos + 2 > len(der) or der[pos] != 0x02:
        raise ValueError("Signature DER s marker missing")
    s_len = der[pos + 1]
    pos += 2
    if s_len == 0:
        raise ValueError("Signature DER s value is empty")
    if pos + s_len > len(der):
        raise ValueError("Signature DER s value is truncated")
    if pos + s_len < len(der):
        raise ValueError("Signature DER encoding has trailing bytes")
    s_bytes = der[pos : pos + s_len]
    if s_bytes[0] & 0x80:
        raise ValueError("Signature DER s value is negative")
    if s_len > 1 and s_bytes[0] == 0 and not s_bytes[1] & 0x80:
        raise ValueError("Signature DER s value has an unnecessary leading zero")
    s = int.from_bytes(s_bytes, "big")

    return r, s


_Point = tuple[int, int] | None  # affine point, None = point at infinity


def _point_add(p: _Point, q: _Point) -> _Point:
    """Add two points on secp256k1 (affine coordinates)."""
    if p is None:
        return q
    if q is None:
        return p
    px, py = p
    qx, qy = q
    if px == qx:
        if (py + qy) % _SECP256K1_P == 0:
            return None
        # Point doubling
        lam = (3 * px * px) * pow(2 * py, -1, _SECP256K1_P) % _SECP256K1_P
    else:
        lam = (qy - py) * pow(qx - px, -1, _SECP256K1_P) % _SECP256K1_P
    rx = (lam * lam - px - qx) % _SECP256K1_P
    ry = (lam * (px - rx) - py) % _SECP256K1_P
    return rx, ry


def _point_mul(k: int, p: _Point) -> _Point:
    """Multiply a secp256k1 point by a scalar (double-and-add)."""
    result: _Point = None
    addend = p
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _decompress_pubkey(pubkey: bytes) -> tuple[int, int]:
    """Decompress a 33-byte compressed secp256k1 public key."""
    if len(pubkey) != 33 or pubkey[0] not in (0x02, 0x03):
        raise ValueError("Public key is not a compressed secp256k1 point")
    x = int.from_bytes(pubkey[1:], "big")
    if x >= _SECP256K1_P:
        raise ValueError("Public key x coordinate is out of range")
    y_squared = (pow(x, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_squared, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if y * y % _SECP256K1_P != y_squared:
        raise ValueError("Public key is not on the secp256k1 curve")
    if y % 2 != pubkey[0] % 2:
        y = _SECP256K1_P - y
    return x, y


def _verify_ecdsa_signature(pubkey: bytes, sighash: bytes, der_sig: bytes) -> bool:
    """Verify a DER ECDSA signature over sighash with the compressed pubkey."""
    r, s = _parse_der_signature(der_sig)
    if not (1 <= r < _SECP256K1_N and 1 <= s < _SECP256K1_N):
        return False

    point = _decompress_pubkey(pubkey)
    z = int.from_bytes(sighash, "big")
    s_inv = pow(s, -1, _SECP256K1_N)
    u1 = z * s_inv % _SECP256K1_N
    u2 = r * s_inv % _SECP256K1_N
    result = _point_add(
        _point_mul(u1, (_SECP256K1_GX, _SECP256K1_GY)),
        _point_mul(u2, point),
    )
    if result is None:
        return False
    return result[0] % _SECP256K1_N == r


def verify_bond_signature(
    tx: _UnsignedTxFields,
    witness_script: bytes,
    utxo_value: int,
    pubkey: bytes,
    signature: bytes,
) -> None:
    """Verify the partial signature; raise ValueError if it is invalid.

    ``signature`` is the PSBT partial signature value: DER signature followed
    by the SIGHASH_ALL byte (already validated by the caller).
    """
    sighash = _compute_bip143_sighash(tx, witness_script, utxo_value)
    der_sig = signature[:-1]
    if not _verify_ecdsa_signature(pubkey, sighash, der_sig):
        raise ValueError(
            "Signature verification failed: the partial signature is not a "
            "valid signature by the witness_script pubkey over this "
            "transaction (BIP143 SIGHASH_ALL). The signing device did not "
            "produce a usable bond spend signature."
        )

    _, s = _parse_der_signature(der_sig)
    if s > _SECP256K1_N // 2:
        print(
            "WARNING: signature uses a high-S value; the final transaction "
            "is valid but non-standard and may be rejected by relay policy.",
            file=sys.stderr,
        )


@dataclass
class SignedBondPSBT:
    """Parsed fields of a signed single-input bond PSBT."""

    unsigned_tx: bytes
    tx_fields: _UnsignedTxFields
    signature: bytes
    witness_script: bytes
    pubkey: bytes
    utxo_value: int


def parse_signed_bond_psbt(psbt_b64: str) -> SignedBondPSBT:
    """Extract the fields needed to finalize a signed single-input bond PSBT."""
    psbt_clean = "".join(psbt_b64.split())
    try:
        raw = base64.b64decode(psbt_clean, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64 PSBT: {e}") from e

    if not raw.startswith(b"psbt\xff"):
        raise ValueError("Invalid PSBT: missing magic bytes")

    pos = 5
    unsigned_tx: bytes | None = None
    global_map_complete = False

    # Global map.
    while pos < len(raw):
        key, value, pos = _read_psbt_pair(raw, pos)
        if key is None:
            global_map_complete = True
            break
        assert value is not None
        if key[0] == 0x00:  # PSBT_GLOBAL_UNSIGNED_TX
            unsigned_tx = value

    if not global_map_complete:
        raise ValueError("PSBT global map is truncated")
    if unsigned_tx is None:
        raise ValueError("PSBT missing unsigned transaction")

    tx_fields = _parse_unsigned_tx(unsigned_tx)

    partial_sigs: list[bytes] = []
    partial_sig_pubkeys: list[bytes] = []
    witness_script: bytes | None = None
    witness_utxo_script: bytes | None = None
    utxo_value: int | None = None
    input_map_complete = False

    # Input map for the single input.
    while pos < len(raw):
        key, value, pos = _read_psbt_pair(raw, pos)
        if key is None:
            input_map_complete = True
            break
        assert value is not None
        key_type = key[0]
        if key_type == 0x01:  # PSBT_IN_WITNESS_UTXO
            witness_utxo_script = _extract_witness_utxo_script(value)
            utxo_value = struct.unpack("<Q", value[:8])[0]
        elif key_type == 0x02:  # PSBT_IN_PARTIAL_SIG
            pubkey = key[1:]
            if len(pubkey) != 33:
                raise ValueError(
                    "Partial signature key does not contain a compressed pubkey"
                )
            partial_sig_pubkeys.append(pubkey)
            partial_sigs.append(value)
        elif key_type == 0x05:  # PSBT_IN_WITNESS_SCRIPT
            witness_script = value

    if not input_map_complete:
        raise ValueError("PSBT input map is truncated")
    if not partial_sigs:
        raise ValueError("PSBT missing partial signature")
    if len(partial_sigs) > 1:
        raise ValueError("Expected exactly 1 partial signature")
    if witness_script is None:
        raise ValueError("PSBT missing witness_script")
    if witness_utxo_script is None or utxo_value is None:
        raise ValueError("PSBT missing witness_utxo")

    _validate_p2wsh_script(witness_utxo_script, witness_script)
    script_pubkey = _extract_freeze_script_pubkey(witness_script)

    signature = partial_sigs[0]
    if partial_sig_pubkeys[0] != script_pubkey:
        raise ValueError(
            "Partial signature pubkey does not match witness_script pubkey"
        )
    if not signature or signature[-1] != 0x01:
        raise ValueError("Partial signature is missing SIGHASH_ALL byte")

    return SignedBondPSBT(
        unsigned_tx=unsigned_tx,
        tx_fields=tx_fields,
        signature=signature,
        witness_script=witness_script,
        pubkey=script_pubkey,
        utxo_value=utxo_value,
    )


def finalize_bond_psbt(psbt_b64: str) -> str:
    """Return final raw transaction hex from a signed and verified bond PSBT.

    Raises ValueError if the PSBT is malformed or the partial signature does
    not verify against the witness script pubkey.
    """
    data = parse_signed_bond_psbt(psbt_b64)

    verify_bond_signature(
        tx=data.tx_fields,
        witness_script=data.witness_script,
        utxo_value=data.utxo_value,
        pubkey=data.pubkey,
        signature=data.signature,
    )

    witness = (
        _encode_varint(2)
        + _encode_varint(len(data.signature))
        + data.signature
        + _encode_varint(len(data.witness_script))
        + data.witness_script
    )

    # PSBT unsigned txs are non-witness serializations. For the single-input
    # bond spend, insert marker/flag after nVersion and one witness stack before
    # nLockTime.
    unsigned_tx = data.unsigned_tx
    signed_tx = (
        unsigned_tx[:4] + b"\x00\x01" + unsigned_tx[4:-4] + witness + unsigned_tx[-4:]
    )
    return signed_tx.hex()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize a signed fidelity bond PSBT into raw transaction hex.",
    )
    parser.add_argument("psbt", nargs="?", help="Base64-encoded signed PSBT")
    parser.add_argument("--file", "-f", type=Path, help="Read signed PSBT from file")
    args = parser.parse_args()

    if args.file is not None:
        psbt_b64 = args.file.read_text().strip()
    elif args.psbt:
        psbt_b64 = args.psbt.strip()
    else:
        parser.error("Provide a signed PSBT argument or --file")

    try:
        signed_hex = finalize_bond_psbt(psbt_b64)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        "Signature verified (BIP143 SIGHASH_ALL over the CLTV witness script).",
        file=sys.stderr,
    )
    print(signed_hex)


if __name__ == "__main__":
    main()
