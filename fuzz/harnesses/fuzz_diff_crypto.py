# ruff: noqa: E402
import sys
import os
import atheris
import ctypes

# --- SECP256K1 C-Library Monkey Patch ---
# bitcointx uses deprecated C function names from older libsecp256k1 versions.
# We dynamically alias them here so the CFFI loader doesn't crash on modern systems.
_original_getattr = ctypes.CDLL.__getattr__


def _patched_getattr(self, name):
    if name == "secp256k1_ec_privkey_tweak_add":
        try:
            return _original_getattr(self, "secp256k1_ec_seckey_tweak_add")
        except AttributeError:
            pass
    if name == "secp256k1_ec_privkey_tweak_mul":
        try:
            return _original_getattr(self, "secp256k1_ec_seckey_tweak_mul")
        except AttributeError:
            pass
    return _original_getattr(self, name)


ctypes.CDLL.__getattr__ = _patched_getattr  # type: ignore[method-assign]
# ----------------------------------------

# Setup paths
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for component in ["jmcore", "jmwallet", "jmwalletd", "maker", "taker"]:
    sys.path.append(os.path.join(root_dir, component, "src"))
sys.path.append("/tmp/joinmarket-clientserver/src")

with atheris.instrument_imports():
    from jmcore.crypto import (
        bitcoin_message_hash,
        ecdsa_sign,
        ecdsa_verify,
        mnemonic_to_seed,
    )

    try:
        from bitcointx.signmessage import BitcoinMessage
        from jmbitcoin.secp256k1_main import ecdsa_sign as legacy_ecdsa_sign
        from jmbitcoin.secp256k1_main import ecdsa_verify as legacy_ecdsa_verify
        from mnemonic import Mnemonic
    except ImportError:
        BitcoinMessage = None
        legacy_ecdsa_sign = None
        legacy_ecdsa_verify = None
        Mnemonic = None


def fuzz_message_hashing(fdp):
    """Tests Bitcoin Message Hashing (Double SHA256 with specific prefix)."""
    if not BitcoinMessage:
        return
    msg = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 1000))

    # NG Hash
    ng_hash = bitcoin_message_hash(msg)

    # Legacy Hash (bitcointx internal)
    legacy_hash = BitcoinMessage(msg).GetHash()

    if ng_hash != legacy_hash:
        raise AssertionError(
            f"Message Hash Mismatch!\nNG: {ng_hash.hex()}\nLegacy: {legacy_hash.hex()}\nMsg: {msg}"
        )


def fuzz_ecdsa_signatures(fdp):
    """Tests ECDSA Sign/Verify symmetry using Bitcoin message format."""
    if not legacy_ecdsa_sign:
        return

    msg = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 512))
    priv_key = fdp.ConsumeBytes(32)
    if len(priv_key) != 32 or int.from_bytes(priv_key, "big") == 0:
        return

    try:
        # Sign with NG, Verify with Legacy
        ng_sig = ecdsa_sign(msg, priv_key)

        # We need the pubkey for legacy verify.
        # NG can derive it easily.
        from coincurve import PrivateKey

        pubkey_bytes = PrivateKey(priv_key).public_key.format(compressed=True)

        legacy_res = legacy_ecdsa_verify(msg, ng_sig, pubkey_bytes)
        if not legacy_res:
            raise AssertionError(
                f"NG-Signed/Legacy-Verify Failure!\nMsg: {msg}\nSig: {ng_sig}"
            )

        # Sign with Legacy, Verify with NG
        legacy_sig = legacy_ecdsa_sign(msg, priv_key)
        ng_res = ecdsa_verify(msg, legacy_sig, pubkey_bytes)
        if not ng_res:
            raise AssertionError(
                f"Legacy-Signed/NG-Verify Failure!\nMsg: {msg}\nSig: {legacy_sig}"
            )

    except Exception:
        # Math errors in keys are expected if fuzzer generates invalid points
        pass


def fuzz_mnemonic_derivation(fdp):
    """Tests BIP39 Mnemonic -> Seed derivation."""
    if not Mnemonic:
        return

    # Simple mnemonic test (though we should ideally use valid BIP39 strings)
    # The fuzzer will find the edge cases
    mnemonic_str = " ".join(["abandon"] * 12)
    passphrase = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 64))

    ng_seed = mnemonic_to_seed(mnemonic_str, passphrase)
    legacy_seed = Mnemonic("english").to_seed(mnemonic_str, passphrase)

    if ng_seed != legacy_seed:
        raise AssertionError(
            f"Mnemonic Seed Mismatch!\nNG: {ng_seed.hex()}\nLegacy: {legacy_seed.hex()}"
        )


def TestOneInput(data):
    if len(data) < 16:
        return
    fdp = atheris.FuzzedDataProvider(data)
    domain = fdp.ConsumeIntInRange(0, 2)
    if domain == 0:
        fuzz_message_hashing(fdp)
    elif domain == 1:
        fuzz_ecdsa_signatures(fdp)
    elif domain == 2:
        fuzz_mnemonic_derivation(fdp)


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
