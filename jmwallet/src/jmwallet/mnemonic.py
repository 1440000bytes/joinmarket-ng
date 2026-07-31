"""BIP39 mnemonic generation from operating-system entropy."""

from __future__ import annotations

import secrets

from mnemonic import Mnemonic

SUPPORTED_ENTROPY_BITS = frozenset({128, 160, 192, 224, 256})


class EntropySourceError(RuntimeError):
    """Raised when the operating-system entropy source violates its contract."""


def generate_wallet_entropy(strength: int = 256) -> bytes:
    """Return a supported BIP39 entropy length from the operating-system CSPRNG."""
    if strength not in SUPPORTED_ENTROPY_BITS:
        allowed = ", ".join(str(bits) for bits in sorted(SUPPORTED_ENTROPY_BITS))
        raise ValueError(f"strength must be one of: {allowed}")

    expected_length = strength // 8
    entropy = secrets.token_bytes(expected_length)
    if len(entropy) != expected_length:
        raise EntropySourceError(
            f"entropy source returned {len(entropy)} bytes, expected {expected_length}"
        )
    return entropy


def mnemonic_from_entropy(entropy: bytes) -> str:
    """Encode supported raw entropy as an English BIP39 mnemonic."""
    strength = len(entropy) * 8
    if strength not in SUPPORTED_ENTROPY_BITS:
        allowed = ", ".join(str(bits // 8) for bits in sorted(SUPPORTED_ENTROPY_BITS))
        raise ValueError(f"entropy length must be one of these byte counts: {allowed}")
    return Mnemonic("english").to_mnemonic(entropy)


def generate_wallet_mnemonic(strength: int = 256) -> str:
    """Generate an English BIP39 mnemonic from operating-system entropy."""
    return mnemonic_from_entropy(generate_wallet_entropy(strength))
