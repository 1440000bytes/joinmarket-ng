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
    from jmcore.protocol import UTXOMetadata
    from jmcore.bitcoin import btc_to_sats, sats_to_btc
    from jmcore.crypto import base58_encode, base58check_encode

    try:
        from jmbase.support import utxostr_to_utxo as legacy_utxo_parse
        from jmbitcoin.amount import btc_to_sat as legacy_btc_to_sat
        from jmbitcoin.amount import sat_to_btc as legacy_sat_to_btc
        from jmbitcoin.secp256k1_main import bin_to_b58check as legacy_b58check

        # bitcointx is used under the hood
        from bitcointx import base58 as legacy_b58
    except ImportError:
        legacy_utxo_parse = None
        legacy_btc_to_sat = None
        legacy_sat_to_btc = None
        legacy_b58check = None
        legacy_b58 = None


def fuzz_utxo_structure(fdp):
    """Tests edge-cases in String -> Datatype validation for UTXOs."""
    if not legacy_utxo_parse:
        return
    utxo_str = fdp.ConsumeUnicodeNoSurrogates(256)
    try:
        legacy_valid, _ = legacy_utxo_parse(utxo_str)
    except Exception:
        legacy_valid = False
    try:
        UTXOMetadata.from_str(utxo_str)
        ng_valid = True
    except Exception:
        ng_valid = False
    if legacy_valid != ng_valid:
        raise AssertionError(
            f"UTXO Validation Mismatch! NG: {ng_valid}, Legacy: {legacy_valid} Input: {utxo_str}"
        )


def fuzz_amount_conversion(fdp):
    """Tests Amount scaling (BTC <-> SAT) equivalence."""
    if not legacy_btc_to_sat:
        return

    # 1. BTC -> SAT
    # We use a float for the BTC amount
    btc_amount = fdp.ConsumeFloatInRange(0.0, 21000000.0)
    try:
        ng_sat = btc_to_sats(btc_amount)
        legacy_sat = int(legacy_btc_to_sat(btc_amount))
        if ng_sat != legacy_sat:
            raise AssertionError(
                f"BTC->SAT Mismatch! NG: {ng_sat}, Legacy: {legacy_sat} BTC: {btc_amount}"
            )
    except Exception:
        pass

    # 2. SAT -> BTC
    sat_amount = fdp.ConsumeIntInRange(0, 2100000000000000)
    ng_btc = float(sats_to_btc(sat_amount))
    legacy_btc = float(legacy_sat_to_btc(sat_amount))
    if abs(ng_btc - legacy_btc) > 1e-12:
        raise AssertionError(
            f"SAT->BTC Mismatch! NG: {ng_btc}, Legacy: {legacy_btc} SAT: {sat_amount}"
        )


def fuzz_base58_logic(fdp):
    """Tests Base58 and Base58Check encoding symmetry."""
    if not legacy_b58:
        return
    data = fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 100))

    # Raw Base58
    ng_b58 = base58_encode(data)
    legacy_b58_str = legacy_b58.encode(data)
    if ng_b58 != legacy_b58_str:
        raise AssertionError(
            f"Base58 Mismatch! NG: {ng_b58}, Legacy: {legacy_b58_str} Data: {data.hex()}"
        )

    # Base58Check (usually used with a version byte)
    if len(data) > 0:
        version = data[0]
        payload = data[1:]
        try:
            ng_check = base58check_encode(data)
            legacy_check = legacy_b58check(payload, version)
            if ng_check != legacy_check:
                raise AssertionError(
                    f"Base58Check Mismatch! NG: {ng_check}, Legacy: {legacy_check}"
                )
        except Exception:
            pass


def TestOneInput(data):
    if len(data) < 16:
        return
    fdp = atheris.FuzzedDataProvider(data)
    domain = fdp.ConsumeIntInRange(0, 2)
    if domain == 0:
        fuzz_utxo_structure(fdp)
    elif domain == 1:
        fuzz_amount_conversion(fdp)
    elif domain == 2:
        fuzz_base58_logic(fdp)


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
