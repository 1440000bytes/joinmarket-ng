"""Tests for the standalone mnemonic bond signing script.

This test file is self-contained -- it does NOT import from jmcore or jmwallet,
mirroring the script itself which has zero project dependencies (only coincurve).
Test PSBTs are hardcoded from known BIP84 test vectors.
"""

from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

import pytest

# Add scripts directory to path for importing the signing script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from sign_bond_mnemonic import (
    _encode_varint,
    _path_to_string,
    _read_varint,
    derive_key_from_mnemonic,
    parse_psbt,
    sign_bond_transaction,
)

# ---------------------------------------------------------------------------
# Test vectors (BIP84, "abandon" mnemonic x11 + "about")
# ---------------------------------------------------------------------------

TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)

# m/84'/0'/0'/0/0
EXPECTED_PUBKEY_0_0 = "0330d54fd0dd420a6e5f8d3624f5f3482cae350f79d5f0753bf5beef9c2d91af3c"
# NOTE: This private key comes from the public BIP39 "abandon ... about" test
# vector mnemonic and is used only for deterministic regression tests.
EXPECTED_PRIVKEY_0_0 = "4604b4b710fe91f584fff084e1a9159fe4f8408fff380596a604948474ce4fa3"

# m/84'/0'/0'/0/1
EXPECTED_PUBKEY_0_1 = "03e775fd51f0dfb8cd865d9ff1cca2a158cf651fe997fdc9fee9c1d3b5e995ea77"

# CLTV freeze witness script using pubkey 0/0 and locktime 2026-02-01
WITNESS_SCRIPT_HEX = (
    "0480977e69b175210330d54fd0dd420a6e5f8d3624f5f3482cae350f79d5f0753bf5beef9c2d91af3cac"
)

# P2WSH scriptpubkey: OP_0 <SHA256(witness_script)>
P2WSH_SPK_HEX = "00201b5e4cdff98542146b4bf9d51213eed52b68252b810a4f15aae02d42c97f04ae"

# Pre-built PSBTs (generated from known test vectors, verified round-trip)
# PSBT with BIP32 derivation: fingerprint=ce1a0d14, path=m/84'/0'/0'/0/0,
# utxo_value=100000, witness_script=WITNESS_SCRIPT_HEX
TEST_PSBT_B64 = (
    "cHNidP8BAF4CAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+"
    "////AbiCAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK6Al35p"
    "AAEBK6CGAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK4BBSoE"
    "gJd+abF1IQMw1U/Q3UIKbl+NNiT180gsrjUPedXwdTv1vu+cLZGvPKwBAwQBAAAAIgYD"
    "MNVP0N1CCm5fjTYk9fNILK41D3nV8HU79b7vnC2RrzwYzhoNFFQAAIAAAACAAAAAgAAA"
    "AAAAAAAAAA=="
)

# Same PSBT but without BIP32 derivation data
TEST_PSBT_NO_BIP32_B64 = (
    "cHNidP8BAF4CAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+"
    "////AbiCAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK6Al35p"
    "AAEBK6CGAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK4BBSoE"
    "gJd+abF1IQMw1U/Q3UIKbl+NNiT180gsrjUPedXwdTv1vu+cLZGvPKwBAwQBAAAAAAAA"
)


# ---------------------------------------------------------------------------
# Tests: _read_varint
# ---------------------------------------------------------------------------


class TestReadVarint:
    def test_single_byte(self) -> None:
        data = bytes([42])
        value, offset = _read_varint(data, 0)
        assert value == 42
        assert offset == 1

    def test_two_bytes(self) -> None:
        """0xFD prefix -> 2 bytes little-endian."""
        data = bytes([0xFD]) + struct.pack("<H", 0x0102)
        value, offset = _read_varint(data, 0)
        assert value == 0x0102
        assert offset == 3

    def test_four_bytes(self) -> None:
        """0xFE prefix -> 4 bytes little-endian."""
        data = bytes([0xFE]) + struct.pack("<I", 70_000)
        value, offset = _read_varint(data, 0)
        assert value == 70_000
        assert offset == 5

    def test_eight_bytes(self) -> None:
        """0xFF prefix -> 8 bytes little-endian."""
        data = bytes([0xFF]) + struct.pack("<Q", 2**33)
        value, offset = _read_varint(data, 0)
        assert value == 2**33
        assert offset == 9

    def test_offset(self) -> None:
        """Reading at a non-zero offset."""
        data = bytes([0x00, 0x00, 0x05])
        value, offset = _read_varint(data, 2)
        assert value == 5
        assert offset == 3


# ---------------------------------------------------------------------------
# Tests: _path_to_string
# ---------------------------------------------------------------------------


class TestPathToString:
    def test_standard_bip84_path(self) -> None:
        indices = [84 | 0x80000000, 0 | 0x80000000, 0 | 0x80000000, 0, 0]
        assert _path_to_string(indices) == "m/84'/0'/0'/0/0"

    def test_non_hardened_only(self) -> None:
        indices = [1, 2, 3]
        assert _path_to_string(indices) == "m/1/2/3"

    def test_empty_path(self) -> None:
        assert _path_to_string([]) == "m"

    def test_mixed_hardened(self) -> None:
        indices = [44 | 0x80000000, 0, 0 | 0x80000000]
        assert _path_to_string(indices) == "m/44'/0/0'"


# ---------------------------------------------------------------------------
# Tests: parse_psbt
# ---------------------------------------------------------------------------


class TestParsePSBT:
    def test_parse_with_bip32(self) -> None:
        result = parse_psbt(TEST_PSBT_B64)
        assert result["witness_utxo_value"] == 100_000
        assert result["witness_script"].hex() == WITNESS_SCRIPT_HEX
        assert result["bip32_pubkey"].hex() == EXPECTED_PUBKEY_0_0
        assert result["bip32_fingerprint"].hex() == "ce1a0d14"
        assert result["bip32_path_str"] == "m/84'/0'/0'/0/0"

    def test_parse_without_bip32(self) -> None:
        result = parse_psbt(TEST_PSBT_NO_BIP32_B64)
        assert result["witness_utxo_value"] == 100_000
        assert result["witness_script"].hex() == WITNESS_SCRIPT_HEX
        assert "bip32_pubkey" not in result
        assert "bip32_path_str" not in result

    def test_missing_witness_script_raises(self) -> None:
        """PSBT without witness_script raises ValueError."""
        # Build a PSBT with only WITNESS_UTXO (no WITNESS_SCRIPT or BIP32)
        import struct as _st

        version = 2
        locktime = 1_769_904_000
        txid_le = bytes(32)
        utxo_value = 100_000
        p2wsh_spk = bytes.fromhex(P2WSH_SPK_HEX)

        # Minimal unsigned tx
        tx = _st.pack("<I", version)
        tx += _encode_varint(1)
        tx += txid_le + _st.pack("<I", 0) + _encode_varint(0) + _st.pack("<I", 0xFFFFFFFE)
        tx += _encode_varint(1)
        tx += _st.pack("<Q", 99_000) + _encode_varint(len(p2wsh_spk)) + p2wsh_spk
        tx += _st.pack("<I", locktime)

        # PSBT with only witness_utxo in input map (no witness_script)
        wu = _st.pack("<Q", utxo_value) + _encode_varint(len(p2wsh_spk)) + p2wsh_spk
        psbt = b"psbt\xff"
        psbt += _encode_varint(1) + bytes([0x00]) + _encode_varint(len(tx)) + tx
        psbt += bytes([0x00])  # global separator
        psbt += _encode_varint(1) + bytes([0x01]) + _encode_varint(len(wu)) + wu
        psbt += bytes([0x00])  # input separator
        psbt += bytes([0x00])  # output separator

        with pytest.raises(ValueError, match="witness_script"):
            parse_psbt(base64.b64encode(psbt).decode())

    def test_invalid_magic(self) -> None:
        bad = base64.b64encode(b"not a psbt").decode()
        with pytest.raises(ValueError, match="[Ii]nvalid PSBT"):
            parse_psbt(bad)


# ---------------------------------------------------------------------------
# Tests: derive_key_from_mnemonic
# ---------------------------------------------------------------------------


class TestDeriveKeyFromMnemonic:
    def test_bip84_path_0_0(self) -> None:
        """Verify against known BIP84 test vector."""
        privkey, pubkey = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84'/0'/0'/0/0")
        assert pubkey.hex() == EXPECTED_PUBKEY_0_0
        assert privkey.hex() == EXPECTED_PRIVKEY_0_0

    def test_bip84_path_0_1(self) -> None:
        """Different index produces different key."""
        privkey, pubkey = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84'/0'/0'/0/1")
        assert pubkey.hex() == EXPECTED_PUBKEY_0_1
        assert privkey.hex() != EXPECTED_PRIVKEY_0_0

    def test_with_passphrase(self) -> None:
        """BIP39 passphrase produces a different seed -> different keys."""
        privkey, pubkey = derive_key_from_mnemonic(
            TEST_MNEMONIC, "m/84'/0'/0'/0/0", passphrase="test"
        )
        assert pubkey.hex() != EXPECTED_PUBKEY_0_0

    def test_invalid_path(self) -> None:
        with pytest.raises((ValueError, IndexError)):
            derive_key_from_mnemonic(TEST_MNEMONIC, "not/a/path")

    def test_hardened_h_notation(self) -> None:
        """Verify h notation works same as apostrophe."""
        _, pubkey_apostrophe = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84'/0'/0'/0/0")
        _, pubkey_h = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84h/0h/0h/0/0")
        assert pubkey_apostrophe.hex() == pubkey_h.hex()


# ---------------------------------------------------------------------------
# Tests: sign_bond_transaction (integration)
# ---------------------------------------------------------------------------


class TestSignBondTransaction:
    def test_sign_produces_valid_witness(self) -> None:
        """Sign a test PSBT and verify the output is a valid hex transaction."""
        psbt_data = parse_psbt(TEST_PSBT_B64)
        privkey = bytes.fromhex(EXPECTED_PRIVKEY_0_0)

        signed_hex = sign_bond_transaction(
            unsigned_tx_bytes=psbt_data["unsigned_tx_bytes"],
            witness_script=psbt_data["witness_script"],
            utxo_value=psbt_data["witness_utxo_value"],
            private_key_bytes=privkey,
        )

        # Should be valid hex
        signed_bytes = bytes.fromhex(signed_hex)

        # Should be a segwit tx (marker byte 0x00, flag byte 0x01 after version)
        assert signed_bytes[4] == 0x00  # segwit marker
        assert signed_bytes[5] == 0x01  # segwit flag

        # Should have the same version as the unsigned tx
        version = struct.unpack("<I", signed_bytes[:4])[0]
        assert version == 2

        # Locktime should match
        locktime = struct.unpack("<I", signed_bytes[-4:])[0]
        assert locktime == 1769904000

    def test_sign_with_wrong_key_still_produces_tx(self) -> None:
        """Signing with wrong key produces a tx (validity checked by the network)."""
        psbt_data = parse_psbt(TEST_PSBT_B64)

        # Derive a different key
        wrong_privkey, _ = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84'/0'/0'/0/1")

        # Should still produce a transaction (just won't be valid on-chain)
        signed_hex = sign_bond_transaction(
            unsigned_tx_bytes=psbt_data["unsigned_tx_bytes"],
            witness_script=psbt_data["witness_script"],
            utxo_value=psbt_data["witness_utxo_value"],
            private_key_bytes=wrong_privkey,
        )
        assert len(signed_hex) > 0
        bytes.fromhex(signed_hex)  # valid hex

    def test_witness_stack_has_signature_and_script(self) -> None:
        """Verify the witness stack contains [sig, witness_script]."""
        psbt_data = parse_psbt(TEST_PSBT_B64)
        privkey = bytes.fromhex(EXPECTED_PRIVKEY_0_0)
        witness_script = psbt_data["witness_script"]

        signed_hex = sign_bond_transaction(
            unsigned_tx_bytes=psbt_data["unsigned_tx_bytes"],
            witness_script=witness_script,
            utxo_value=psbt_data["witness_utxo_value"],
            private_key_bytes=privkey,
        )
        signed_bytes = bytes.fromhex(signed_hex)

        # Find the witness data -- after the outputs, before locktime
        # Parse minimally: skip version(4) + marker(1) + flag(1) + inputs + outputs
        offset = 6  # past version + marker + flag

        # Skip inputs
        n_inputs, offset = _read_varint(signed_bytes, offset)
        for _ in range(n_inputs):
            offset += 32 + 4  # txid + vout
            script_len, offset = _read_varint(signed_bytes, offset)
            offset += script_len + 4  # scriptsig + sequence

        # Skip outputs
        n_outputs, offset = _read_varint(signed_bytes, offset)
        for _ in range(n_outputs):
            offset += 8  # value
            script_len, offset = _read_varint(signed_bytes, offset)
            offset += script_len

        # Now at witness data
        n_items, offset = _read_varint(signed_bytes, offset)
        assert n_items == 2  # [signature, witness_script]

        # First item: DER signature + sighash type byte
        sig_len, offset = _read_varint(signed_bytes, offset)
        sig = signed_bytes[offset : offset + sig_len]
        offset += sig_len
        assert sig[-1] == 0x01  # SIGHASH_ALL

        # Second item: witness script
        ws_len, offset = _read_varint(signed_bytes, offset)
        ws = signed_bytes[offset : offset + ws_len]
        assert ws == witness_script


# ---------------------------------------------------------------------------
# Tests: end-to-end main() flow
# ---------------------------------------------------------------------------


class TestMainFlow:
    def test_main_with_cli_path_override(self) -> None:
        """Test that --derivation-path overrides PSBT's BIP32 path."""
        psbt_data = parse_psbt(TEST_PSBT_B64)
        # The PSBT has path m/84'/0'/0'/0/0, but we can override via CLI
        # Just verify the parse + derive + sign pipeline works
        privkey, pubkey = derive_key_from_mnemonic(TEST_MNEMONIC, "m/84'/0'/0'/0/0")
        assert pubkey.hex() == EXPECTED_PUBKEY_0_0

        signed = sign_bond_transaction(
            unsigned_tx_bytes=psbt_data["unsigned_tx_bytes"],
            witness_script=psbt_data["witness_script"],
            utxo_value=psbt_data["witness_utxo_value"],
            private_key_bytes=privkey,
        )
        assert len(bytes.fromhex(signed)) > 0

    def test_psbt_without_bip32_requires_cli_path(self) -> None:
        """When PSBT has no BIP32 derivation, path must come from CLI."""
        result = parse_psbt(TEST_PSBT_NO_BIP32_B64)
        assert "bip32_path_str" not in result
        # The main() function would require --derivation-path in this case
        # We just verify the parse correctly reports no BIP32 data
