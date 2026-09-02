"""
Pytest configuration and fixtures for maker tests.
"""

import pytest
from bitcointx.core.key import CKey


@pytest.fixture
def test_mnemonic() -> str:
    """Test mnemonic (BIP39 test vector)"""
    return (
        "abandon abandon abandon abandon abandon abandon "
        "abandon abandon abandon abandon abandon about"
    )


@pytest.fixture
def test_network() -> str:
    """Test network"""
    return "regtest"


@pytest.fixture
def test_private_key() -> CKey:
    """Generate a test ECDSA private key for fidelity bond tests."""
    return CKey(b"\x01" * 32)


@pytest.fixture
def test_pubkey(test_private_key: CKey) -> bytes:
    """Get compressed public key from test private key."""
    return bytes(test_private_key.pub)
