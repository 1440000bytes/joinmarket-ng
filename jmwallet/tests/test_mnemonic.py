"""Tests for explicit wallet entropy sourcing and BIP39 encoding."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mnemonic import Mnemonic

from jmwallet.mnemonic import (
    EntropySourceError,
    generate_wallet_entropy,
    generate_wallet_mnemonic,
    mnemonic_from_entropy,
)


@pytest.mark.parametrize(
    ("entropy", "expected"),
    [
        (bytes(16), "abandon " * 11 + "about"),
        (bytes(32), "abandon " * 23 + "art"),
    ],
)
def test_mnemonic_from_entropy_matches_bip39_vectors(entropy: bytes, expected: str) -> None:
    assert mnemonic_from_entropy(entropy) == expected


@pytest.mark.parametrize("strength", [128, 160, 192, 224, 256])
def test_generate_wallet_mnemonic_requests_exact_entropy_length(strength: int) -> None:
    entropy = bytes(range(strength // 8))
    with patch("jmwallet.mnemonic.secrets.token_bytes", return_value=entropy) as token_bytes:
        mnemonic = generate_wallet_mnemonic(strength)

    token_bytes.assert_called_once_with(strength // 8)
    assert Mnemonic("english").to_entropy(mnemonic) == entropy


def test_generate_wallet_entropy_propagates_source_failure() -> None:
    with (
        patch(
            "jmwallet.mnemonic.secrets.token_bytes",
            side_effect=OSError("operating-system CSPRNG unavailable"),
        ),
        pytest.raises(OSError, match="CSPRNG unavailable"),
    ):
        generate_wallet_entropy(256)


def test_generate_wallet_entropy_rejects_short_source_output() -> None:
    with (
        patch("jmwallet.mnemonic.secrets.token_bytes", return_value=bytes(31)),
        pytest.raises(EntropySourceError, match="31 bytes, expected 32"),
    ):
        generate_wallet_entropy(256)


@pytest.mark.parametrize("strength", [0, 64, 129, 512])
def test_generate_wallet_entropy_rejects_unsupported_strength(strength: int) -> None:
    with pytest.raises(ValueError, match="strength must be one of"):
        generate_wallet_entropy(strength)


@pytest.mark.parametrize("length", [0, 1, 15, 17, 33])
def test_mnemonic_from_entropy_rejects_unsupported_length(length: int) -> None:
    with pytest.raises(ValueError, match="entropy length"):
        mnemonic_from_entropy(bytes(length))
