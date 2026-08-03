"""CLI tests for cold-wallet commands."""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

import pytest
from coincurve import PrivateKey
from jmcore.crypto import bitcoin_message_hash_bytes
from typer.testing import CliRunner

from jmwallet.cli import app
from jmwallet.wallet.bond_registry import (
    BondRegistry,
    FidelityBondInfo,
    load_registry,
    save_registry,
)

runner = CliRunner()


def test_generate_hot_keypair_does_not_print_private_key_and_writes_key_file():
    """generate-hot-keypair should avoid stdout key leakage and write a 0600 file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        result = runner.invoke(
            app,
            [
                "generate-hot-keypair",
                "--data-dir",
                str(data_dir),
            ],
        )

        assert result.exit_code == 0
        assert "Public Key (hex):" in result.stdout
        assert "Private Key (hex):" not in result.stdout

        key_files = list(data_dir.glob("hot_certificate_key_*.json"))
        assert len(key_files) == 1

        file_mode = key_files[0].stat().st_mode & 0o777
        assert file_mode == 0o600

        payload = json.loads(key_files[0].read_text())
        assert "cert_pubkey" in payload
        assert "cert_privkey" in payload
        assert len(payload["cert_pubkey"]) == 66
        assert len(payload["cert_privkey"]) == 64


def test_prepare_certificate_message_accepts_current_block_override():
    """prepare-certificate-message should work offline with --current-block."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        utxo_key = PrivateKey()
        cert_key = PrivateKey()
        bond = FidelityBondInfo(
            address="bc1qtestpreparecert",
            locktime=1893456000,
            locktime_human="2030-01-01 00:00:00",
            index=0,
            path="external",
            pubkey=utxo_key.public_key.format(compressed=True).hex(),
            witness_script_hex="aa" * 20,
            network="mainnet",
            created_at="2025-01-01T00:00:00",
            cert_pubkey=cert_key.public_key.format(compressed=True).hex(),
        )
        save_registry(BondRegistry(bonds=[bond]), data_dir, "deadbeef")

        result = runner.invoke(
            app,
            [
                "prepare-certificate-message",
                bond.address,
                "--data-dir",
                str(data_dir),
                "--wallet-fingerprint",
                "deadbeef",
                "--current-block",
                "850000",
            ],
        )

    assert result.exit_code == 0
    assert "Current Block:         850000" in result.stdout
    assert "MESSAGE TO SIGN" in result.stdout


@pytest.mark.parametrize("validity_periods", [0, -1])
def test_prepare_certificate_message_rejects_nonpositive_validity(
    validity_periods: int,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        result = runner.invoke(
            app,
            [
                "prepare-certificate-message",
                "bc1qinvalid",
                "--data-dir",
                str(data_dir),
                "--validity-periods",
                str(validity_periods),
                "--current-block",
                "850000",
            ],
        )

        assert result.exit_code == 1
        assert not (data_dir / "certificate_message.txt").exists()


@pytest.mark.parametrize(
    ("cert_expiry", "current_block", "expected_success"),
    [
        (600, 1000, True),
        (600, 600 * 2016, True),
        (600, 600 * 2016 + 1, False),
        (65535, 1000, True),
        (0, 1000, False),
        (-1, 1000, False),
        (65536, 1000, False),
    ],
)
def test_import_certificate_expiry_validation(cert_expiry, current_block, expected_success):
    """Import enforces the wire range and reference expiry boundary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        utxo_key = PrivateKey()
        cert_key = PrivateKey()
        cert_pubkey_hex = cert_key.public_key.format(compressed=True).hex()

        message = f"fidelity-bond-cert|{cert_pubkey_hex}|{cert_expiry}".encode()
        msg_hash = bitcoin_message_hash_bytes(message)
        recoverable = utxo_key.sign_recoverable(msg_hash, hasher=None)
        electrum_sig = bytes([31 + recoverable[64]]) + recoverable[:64]
        sig_b64 = base64.b64encode(electrum_sig).decode()

        bond = FidelityBondInfo(
            address="bc1qtestimportcert",
            locktime=1893456000,
            locktime_human="2030-01-01 00:00:00",
            index=0,
            path="external",
            pubkey=utxo_key.public_key.format(compressed=True).hex(),
            witness_script_hex="bb" * 20,
            network="mainnet",
            created_at="2025-01-01T00:00:00",
            cert_pubkey=cert_pubkey_hex,
            cert_privkey=cert_key.secret.hex(),
        )
        save_registry(BondRegistry(bonds=[bond]), data_dir, "deadbeef")

        result = runner.invoke(
            app,
            [
                "import-certificate",
                bond.address,
                "--data-dir",
                str(data_dir),
                "--wallet-fingerprint",
                "deadbeef",
                "--cert-signature",
                sig_b64,
                "--cert-expiry",
                str(cert_expiry),
                "--current-block",
                str(current_block),
            ],
        )

        loaded = load_registry(data_dir, "deadbeef")
        loaded_bond = loaded.get_bond_by_address(bond.address)

    assert loaded_bond is not None
    if expected_success:
        assert result.exit_code == 0
        assert "CERTIFICATE IMPORTED SUCCESSFULLY" in result.stdout
        assert loaded_bond.cert_expiry == cert_expiry
        assert loaded_bond.cert_signature is not None
    else:
        assert result.exit_code == 1
        assert loaded_bond.cert_expiry is None
        assert loaded_bond.cert_signature is None
