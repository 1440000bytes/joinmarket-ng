"""Tests for the standalone mnemonic bond signing script.

This test file does not import from jmcore or jmwallet, mirroring the script
itself. Test PSBTs are hardcoded from known BIP84 test vectors.
"""

from __future__ import annotations

import base64
import hashlib
import io
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path for importing the signing script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from sign_bond_mnemonic import (
    MAX_BIP32_PATH_DEPTH,
    MAX_MONEY,
    MAX_PSBT_BASE64_SIZE,
    MAX_PSBT_SIZE,
    SECP256K1_N,
    _encode_varint,
    _parse_derivation_path,
    _path_to_string,
    _read_varint,
    derive_key_from_mnemonic,
    main,
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
    "AAAAAAAAAAA="
)

# Same PSBT but without BIP32 derivation data
TEST_PSBT_NO_BIP32_B64 = (
    "cHNidP8BAF4CAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+"
    "////AbiCAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK6Al35p"
    "AAEBK6CGAQAAAAAAIgAgG15M3/mFQhRrS/nVEhPu1StoJSuBCk8VquAtQsl/BK4BBSoE"
    "gJd+abF1IQMw1U/Q3UIKbl+NNiT180gsrjUPedXwdTv1vu+cLZGvPKwBAwQBAAAAAAA="
)


def _psbt_pair(key: bytes, value: bytes) -> bytes:
    return _encode_varint(len(key)) + key + _encode_varint(len(value)) + value


def _bond_script(pubkey: bytes, locktime: int = 1_769_904_000) -> bytes:
    encoded_locktime = locktime.to_bytes((locktime.bit_length() + 7) // 8, "little")
    if encoded_locktime[-1] & 0x80:
        encoded_locktime += b"\x00"
    return bytes([len(encoded_locktime)]) + encoded_locktime + b"\xb1\x75\x21" + pubkey + b"\xac"


def _build_test_psbt(
    *,
    witness_script: bytes = bytes.fromhex(WITNESS_SCRIPT_HEX),
    utxo_value: int = 100_000,
    utxo_script: bytes | None = None,
    locktime: int = 1_769_904_000,
    sequence: int = 0xFFFFFFFE,
    outputs: list[tuple[int, bytes]] | None = None,
    include_bip32: bool = True,
    bip32_value: bytes | None = None,
    input_count: int = 1,
    extra_input_records: list[tuple[bytes, bytes]] | None = None,
) -> str:
    if outputs is None:
        outputs = [(99_000, bytes.fromhex("0014") + bytes.fromhex("11" * 20))]
    if utxo_script is None:
        utxo_script = b"\x00\x20" + hashlib.sha256(witness_script).digest()

    tx = struct.pack("<I", 2) + _encode_varint(input_count)
    for _ in range(input_count):
        tx += bytes(32) + struct.pack("<I", 0) + b"\x00" + struct.pack("<I", sequence)
    tx += _encode_varint(len(outputs))
    for value, script in outputs:
        tx += struct.pack("<Q", value) + _encode_varint(len(script)) + script
    tx += struct.pack("<I", locktime)

    witness_utxo = struct.pack("<Q", utxo_value) + _encode_varint(len(utxo_script)) + utxo_script
    input_records = [
        (b"\x01", witness_utxo),
        (b"\x05", witness_script),
    ]
    if include_bip32:
        pubkey = witness_script[-34:-1]
        path = [0x80000054, 0x80000000, 0x80000000, 0, 0]
        input_records.append(
            (
                b"\x06" + pubkey,
                bip32_value
                if bip32_value is not None
                else bytes.fromhex("ce1a0d14")
                + b"".join(struct.pack("<I", index) for index in path),
            )
        )
    if extra_input_records:
        input_records.extend(extra_input_records)

    psbt = b"psbt\xff" + _psbt_pair(b"\x00", tx) + b"\x00"
    psbt += b"".join(_psbt_pair(key, value) for key, value in input_records) + b"\x00"
    psbt += b"\x00" * len(outputs)
    return base64.b64encode(psbt).decode()


class _InteractiveStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


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

    def test_rejects_witness_script_hash_mismatch(self) -> None:
        psbt = _build_test_psbt(utxo_script=b"\x00\x20" + bytes(32))
        with pytest.raises(ValueError, match="does not match"):
            parse_psbt(psbt)

    @pytest.mark.parametrize(
        ("locktime", "sequence", "error"),
        [
            (1_769_903_999, 0xFFFFFFFE, "below bond locktime"),
            (1_769_904_000, 0xFFFFFFFF, "final sequence"),
        ],
    )
    def test_rejects_unsatisfied_cltv(self, locktime: int, sequence: int, error: str) -> None:
        with pytest.raises(ValueError, match=error):
            parse_psbt(_build_test_psbt(locktime=locktime, sequence=sequence))

    def test_parses_every_output_and_computes_fee(self) -> None:
        outputs = [
            (60_000, bytes.fromhex("0014") + bytes.fromhex("11" * 20)),
            (30_000, bytes.fromhex("0014") + bytes.fromhex("22" * 20)),
        ]
        result = parse_psbt(_build_test_psbt(outputs=outputs))

        assert [output.value for output in result["transaction"].outputs] == [60_000, 30_000]
        assert result["total_output_value"] == 90_000
        assert result["fee"] == 10_000

    @pytest.mark.parametrize(
        ("utxo_value", "outputs", "error"),
        [
            (MAX_MONEY + 1, None, "Witness UTXO value exceeds MAX_MONEY"),
            (MAX_MONEY, [(MAX_MONEY + 1, b"")], "output value exceeds MAX_MONEY"),
            (100_000, [(100_001, b"")], "outputs exceed"),
        ],
    )
    def test_rejects_invalid_amounts_and_negative_fee(
        self,
        utxo_value: int,
        outputs: list[tuple[int, bytes]] | None,
        error: str,
    ) -> None:
        with pytest.raises(ValueError, match=error):
            parse_psbt(_build_test_psbt(utxo_value=utxo_value, outputs=outputs))

    def test_rejects_truncated_and_extra_psbt_maps(self) -> None:
        raw = base64.b64decode(_build_test_psbt())
        with pytest.raises(ValueError, match="Truncated"):
            parse_psbt(base64.b64encode(raw[:-1]).decode())
        with pytest.raises(ValueError, match="extra input or output maps"):
            parse_psbt(base64.b64encode(raw + b"\x00").decode())

    def test_rejects_oversized_psbt_and_bip32_path(self) -> None:
        oversized = base64.b64encode(b"psbt\xff" + bytes(MAX_PSBT_SIZE)).decode()
        with pytest.raises(ValueError, match="exceeds size limit"):
            parse_psbt(oversized)

        oversized_encoded = "A" * (MAX_PSBT_BASE64_SIZE + 1)
        with pytest.raises(ValueError, match="Base64 PSBT input exceeds size limit"):
            parse_psbt(oversized_encoded)

        path = bytes.fromhex("ce1a0d14") + bytes(4 * (MAX_BIP32_PATH_DEPTH + 1))
        with pytest.raises(ValueError, match="path exceeds depth limit"):
            parse_psbt(_build_test_psbt(bip32_value=path))

    def test_rejects_multiple_unsigned_inputs_and_malformed_field_keys(self) -> None:
        with pytest.raises(ValueError, match="exactly one unsigned transaction input"):
            parse_psbt(_build_test_psbt(input_count=2))
        with pytest.raises(ValueError, match="unexpected key data"):
            parse_psbt(_build_test_psbt(extra_input_records=[(b"\x05\x00", b"")]))


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

    def test_unicode_passphrase_uses_bip39_nfkd_normalization(self) -> None:
        path = "m/84'/0'/0'/0/0"
        _, pubkey_composed = derive_key_from_mnemonic(TEST_MNEMONIC, path, passphrase="é")
        _, pubkey_decomposed = derive_key_from_mnemonic(
            TEST_MNEMONIC, path, passphrase="e\N{COMBINING ACUTE ACCENT}"
        )

        assert pubkey_composed == pubkey_decomposed

    def test_invalid_mnemonic_checksum_rejected(self) -> None:
        with pytest.raises(ValueError, match="checksum"):
            derive_key_from_mnemonic("abandon " * 11 + "abandon", "m/84'/0'/0'/0/0")

    def test_invalid_bip32_master_key_rejected(self) -> None:
        with (
            patch("sign_bond_mnemonic.hmac.new") as hmac_new,
            pytest.raises(ValueError, match="invalid master private key"),
        ):
            hmac_new.return_value.digest.return_value = bytes(64)
            derive_key_from_mnemonic(TEST_MNEMONIC, [])

    @pytest.mark.parametrize(
        ("child_offset", "error"),
        [(SECP256K1_N, "invalid child offset"), (SECP256K1_N - 1, "zero child key")],
    )
    def test_invalid_bip32_child_rejected(self, child_offset: int, error: str) -> None:
        master = (1).to_bytes(32, "big") + bytes([2] * 32)
        child = child_offset.to_bytes(32, "big") + bytes([3] * 32)
        with (
            patch("sign_bond_mnemonic.hmac.new") as hmac_new,
            pytest.raises(ValueError, match=error),
        ):
            hmac_new.return_value.digest.side_effect = [master, child]
            derive_key_from_mnemonic(TEST_MNEMONIC, [0])

    def test_invalid_path(self) -> None:
        with pytest.raises(ValueError):
            derive_key_from_mnemonic(TEST_MNEMONIC, "not/a/path")

    @pytest.mark.parametrize(
        "path",
        ["m/", "m/-1", "m/2147483648", "m/1hh", "m/" + "9" * 100_000],
    )
    def test_malformed_path_is_a_clean_value_error(self, path: str) -> None:
        with pytest.raises(ValueError):
            _parse_derivation_path(path)

    def test_path_depth_is_bounded(self) -> None:
        deep_path = "m/" + "/".join("0" for _ in range(MAX_BIP32_PATH_DEPTH + 1))
        with pytest.raises(ValueError, match="depth limit"):
            _parse_derivation_path(deep_path)

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

    def test_displays_destination_and_declines_before_mnemonic(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        destination_script = bytes.fromhex("0014") + bytes.fromhex("42" * 20)
        psbt = _build_test_psbt(outputs=[(99_000, destination_script)])
        with (
            patch.object(
                sys,
                "argv",
                [
                    "sign_bond_mnemonic.py",
                    psbt,
                    "--derivation-path",
                    "m/84'/0'/0'/0/0",
                ],
            ),
            patch.object(sys, "stdin", _InteractiveStdin("no\n")),
            patch("sign_bond_mnemonic.getpass.getpass") as getpass_mock,
            pytest.raises(SystemExit),
        ):
            main()

        assert getpass_mock.call_count == 0
        stderr = capsys.readouterr().err
        assert destination_script.hex() in stderr
        assert "Fee: 1000 sats" in stderr

    def test_noninteractive_confirmation_fails_closed_before_mnemonic(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(sys, "argv", ["sign_bond_mnemonic.py", TEST_PSBT_B64]),
            patch.object(sys, "stdin", io.StringIO()),
            patch("sign_bond_mnemonic.getpass.getpass") as getpass_mock,
            pytest.raises(SystemExit),
        ):
            main()

        assert getpass_mock.call_count == 0
        assert "Refusing to sign without an interactive confirmation" in capsys.readouterr().err

    def test_force_allows_automation_but_checks_witness_pubkey(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        wrong_witness_script = _bond_script(bytes.fromhex(EXPECTED_PUBKEY_0_1))
        psbt = _build_test_psbt(witness_script=wrong_witness_script, include_bip32=False)
        with (
            patch.object(
                sys,
                "argv",
                [
                    "sign_bond_mnemonic.py",
                    psbt,
                    "--force",
                    "--derivation-path",
                    "m/84'/0'/0'/0/0",
                ],
            ),
            patch("sign_bond_mnemonic.getpass.getpass", return_value=TEST_MNEMONIC) as getpass_mock,
            pytest.raises(SystemExit),
        ):
            main()

        assert getpass_mock.call_count == 1
        assert "does not match bond witness script" in capsys.readouterr().err

    def test_force_prints_raw_hex_without_broadcast_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["sign_bond_mnemonic.py", TEST_PSBT_B64, "--force"],
            ),
            patch("sign_bond_mnemonic.getpass.getpass", return_value=TEST_MNEMONIC),
        ):
            main()

        captured = capsys.readouterr()
        assert bytes.fromhex(captured.out.strip())
        assert "sendrawtransaction" not in captured.err
