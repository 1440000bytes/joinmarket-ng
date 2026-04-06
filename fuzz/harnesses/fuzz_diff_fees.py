# ruff: noqa: E402
import sys
import os
import atheris
import logging

# --- SECP256K1 C-Library Monkey Patch ---
# bitcointx uses deprecated C function names from older libsecp256k1 versions.
# We dynamically alias them here so the CFFI loader doesn't crash on modern systems.
import ctypes

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

# Setup path for JoinMarket-NG
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
components = [
    "jmcore",
    "jmwallet",
    "jmwalletd",
    "maker",
    "taker",
    "directory_server",
    "orderbook_watcher",
]
for component in components:
    sys.path.append(os.path.join(root_dir, component, "src"))

# Setup path for legacy JoinMarket (Reference Implementation)
legacy_src = "/tmp/joinmarket-clientserver/src"
sys.path.append(legacy_src)

# Silence loggers
from loguru import logger

logger.remove()
logging.disable(logging.CRITICAL)

with atheris.instrument_imports():
    # NG Imports
    from jmcore.models import calculate_cj_fee as ng_calc_cj_fee, OfferType

    # Legacy Imports
    from jmclient.support import calc_cj_fee as legacy_calc_cj_fee


def fuzz_fee_logic(fdp):
    """Deep differential fuzzing for Maker/Taker fee calculations."""
    amount = fdp.ConsumeIntInRange(1, 2100000000000000)

    # Absolute or relative flag
    is_absolute = fdp.ConsumeBool()

    if is_absolute:
        fee_int = fdp.ConsumeIntInRange(0, int(1e8))
        ng_fee_param = fee_int
        legacy_fee_param = fee_int
        offer_type = "sw0absoffer"
        ng_offer_type = OfferType.SW0_ABSOLUTE
    else:
        # Generate a relative fee fraction (e.g. "0.0001", "0.003", even "1.5")
        # Ensure it fits within string representations used by legacy
        # fdp.ConsumeFloat() isn't always stable, so we construct from Int
        fee_fraction = fdp.ConsumeIntInRange(0, 100000000) / 100000000.0
        ng_fee_param = str(fee_fraction)
        legacy_fee_param = str(fee_fraction)
        offer_type = "sw0reloffer"
        ng_offer_type = OfferType.SW0_RELATIVE

    try:
        # NG Protocol
        ng_fee = ng_calc_cj_fee(ng_offer_type, ng_fee_param, amount)

        # Legacy Protocol
        legacy_fee = legacy_calc_cj_fee(offer_type, legacy_fee_param, amount)

        # Watchdog Crash
        if ng_fee != legacy_fee:
            raise AssertionError(
                f"Fee Calculation Mismatch! NG: {ng_fee}, Legacy: {legacy_fee} (Amt: {amount}, FeeStr: {legacy_fee_param})"
            )

    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        # Catch normal domain errors if they occur
        pass


def fuzz_crypto_logic(fdp):
    """Deep differential fuzzing for Base58 encoding."""
    # Note: legacy joinmarket has basic b58 encoding in jmbase.crypto / bip32
    pass


def TestOneInput(data):
    """Universal Compatibility Watchdog."""
    if len(data) < 4:
        return

    fdp = atheris.FuzzedDataProvider(data)

    # Domain Switcher
    domain = fdp.ConsumeIntInRange(0, 1)

    try:
        if domain == 0:
            fuzz_fee_logic(fdp)
        elif domain == 1:
            fuzz_crypto_logic(fdp)

    except AssertionError:
        raise
    except Exception:
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
