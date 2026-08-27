"""Tests for Bitcoin address validation as used by the send command.

These tests ensure that:
- Valid addresses are accepted and produce the correct scriptPubKey.
- Addresses with invalid checksums (e.g. single-char typos) are rejected.
- Addresses from the wrong network are rejected.
- All four supported networks (mainnet, testnet, signet, regtest) work.
- Case-insensitive decoding works (uppercase addresses from QR codes).
"""

from __future__ import annotations

import threading

import pytest
from bitcointx import ChainParams
from bitcointx.wallet import CCoinAddress, CCoinAddressError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NETWORK_TO_CHAIN = {
    "mainnet": "bitcoin",
    "testnet": "bitcoin/testnet",
    "signet": "bitcoin/signet",
    "regtest": "bitcoin/regtest",
}


def address_to_scriptpubkey(network: str, address: str) -> bytes:
    """Parse and validate an address, returning its scriptPubKey."""
    with ChainParams(NETWORK_TO_CHAIN[network]):
        return bytes(CCoinAddress(address).to_scriptPubKey())


# ---------------------------------------------------------------------------
# Test vectors
# ---------------------------------------------------------------------------

# (network, address, expected_scriptpubkey_hex)
VALID_ADDRESSES = [
    # P2WPKH — mainnet
    (
        "mainnet",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "0014751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    # P2WPKH — regtest
    (
        "regtest",
        "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080",
        "0014751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    # P2WSH — mainnet
    (
        "mainnet",
        "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3",
        "00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262",
    ),
    # P2WPKH — testnet
    (
        "testnet",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
        "0014751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    # P2WPKH — signet (same tb1 prefix as testnet)
    (
        "signet",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
        "0014751e76e8199196d454941c45d1b3a323f1433bd6",
    ),
    # P2WSH — signet (real address from production logs)
    (
        "signet",
        "tb1q8c44zs4rnlvjcwyuhmphp9azpvel55nv95ek4g89jnq4722sxuhsu3epez",
        None,  # just check it parses without error
    ),
]


class TestAddressValidation:
    """CCoinAddress validates checksums and rejects wrong-network addresses."""

    @pytest.mark.parametrize(
        ("network", "address", "expected_spk_hex"),
        VALID_ADDRESSES,
        ids=[
            "mainnet-p2wpkh",
            "regtest-p2wpkh",
            "mainnet-p2wsh",
            "testnet-p2wpkh",
            "signet-p2wpkh",
            "signet-p2wsh-production",
        ],
    )
    def test_valid_address_produces_scriptpubkey(
        self, network: str, address: str, expected_spk_hex: str | None
    ) -> None:
        spk = address_to_scriptpubkey(network, address)
        assert len(spk) > 0
        if expected_spk_hex is not None:
            assert spk.hex() == expected_spk_hex

    @pytest.mark.parametrize(
        ("network", "address"),
        [
            # Last character changed — checksum mismatch
            ("mainnet", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5"),
            # Character changed in the middle
            ("mainnet", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3s4"),
            # Regtest — last char changed
            ("regtest", "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt081"),
            # Signet — last char changed
            ("signet", "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsq"),
        ],
        ids=["mainnet-last-char", "mainnet-mid-char", "regtest-last-char", "signet-last-char"],
    )
    def test_invalid_checksum_rejected(self, network: str, address: str) -> None:
        """A single-character typo must be caught — the original vulnerability.

        The hand-rolled decoder stripped the checksum without verifying it, so
        these addresses would have silently produced wrong scriptPubKeys and
        sent funds to unspendable outputs.
        """
        with pytest.raises(CCoinAddressError):
            address_to_scriptpubkey(network, address)

    @pytest.mark.parametrize(
        ("network", "address"),
        [
            # mainnet address decoded as regtest
            ("regtest", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
            # signet/testnet (tb1) address decoded as mainnet
            ("mainnet", "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"),
            # regtest (bcrt1) address decoded as signet
            ("signet", "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"),
        ],
        ids=["mainnet-as-regtest", "signet-as-mainnet", "regtest-as-signet"],
    )
    def test_wrong_network_rejected(self, network: str, address: str) -> None:
        with pytest.raises(CCoinAddressError):
            address_to_scriptpubkey(network, address)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(CCoinAddressError):
            address_to_scriptpubkey("mainnet", "notanaddress")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(CCoinAddressError):
            address_to_scriptpubkey("mainnet", "")

    def test_uppercase_accepted(self) -> None:
        """Uppercase addresses (e.g. from QR decoders) must be accepted."""
        spk = address_to_scriptpubkey("mainnet", "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
        assert spk.hex() == "0014751e76e8199196d454941c45d1b3a323f1433bd6"


class TestAddressAllocationIsBounded:
    """Allocation must fail loudly instead of deriving addresses forever."""

    @staticmethod
    def _wallet():
        from unittest.mock import MagicMock

        from jmwallet.wallet.service import WalletService

        wallet = WalletService.__new__(WalletService)
        wallet._address_allocation_lock = threading.Lock()
        wallet.metadata_store = None
        wallet.reserved_addresses = set()
        wallet.issued_receive_addresses = set()
        wallet.reserved_address_labels = {}
        wallet.addresses_with_history = set()
        wallet.get_next_address_index = MagicMock(return_value=0)
        wallet.get_address = lambda mixdepth, change, index: f"addr-{mixdepth}-{change}-{index}"
        return wallet

    def test_raises_when_every_candidate_in_range_is_reserved(self) -> None:
        from jmwallet.wallet.service import MAX_ADDRESS_ALLOCATION_CANDIDATES
        from jmwallet.wallet.utxo_metadata import AddressReservationError

        wallet = self._wallet()
        wallet.reserved_addresses = {
            f"addr-0-1-{index}" for index in range(MAX_ADDRESS_ALLOCATION_CANDIDATES)
        }

        with pytest.raises(AddressReservationError):
            wallet.allocate_output_address(0, 1)

    def test_allocates_the_first_free_candidate(self) -> None:
        wallet = self._wallet()
        wallet.reserved_addresses = {"addr-0-1-0", "addr-0-1-1"}

        assert wallet.allocate_output_address(0, 1) == "addr-0-1-2"
