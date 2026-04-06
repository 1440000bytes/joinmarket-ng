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

# Setup path for JoinMarket-NG
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
components = ["jmcore", "jmwallet", "jmwalletd", "maker", "taker"]
for component in components:
    sys.path.append(os.path.join(root_dir, component, "src"))

# Setup path for legacy JoinMarket
legacy_src = "/tmp/joinmarket-clientserver/src"
sys.path.append(legacy_src)

# Disable loggers
from loguru import logger
import logging

logger.remove()
logging.disable(logging.CRITICAL)

with atheris.instrument_imports():
    from jmcore.bond_calc import (
        calculate_timelocked_fidelity_bond_value as ng_calc_bond,
    )

    try:
        from jmclient import FidelityBondMixin

        legacy_calc_bond = FidelityBondMixin.calculate_timelocked_fidelity_bond_value
    except ImportError:
        legacy_calc_bond = None


def TestOneInput(data):
    if len(data) < 32 or not legacy_calc_bond:
        return

    fdp = atheris.FuzzedDataProvider(data)

    # Generate structured parameters for Fidelity Bond calculation
    amount = fdp.ConsumeIntInRange(1, 2100000000000000)

    # Time variables
    current_time = fdp.ConsumeIntInRange(1000000000, 2000000000)

    # Confirm time is usually before or at current time
    confirm_time = fdp.ConsumeIntInRange(1000000000, current_time)

    # Locktime is exclusively in the future up to ~10 years
    locktime = fdp.ConsumeIntInRange(
        current_time, current_time + (10 * 365 * 24 * 60 * 60)
    )

    # Decimal fraction representing interest (e.g. 1.5% -> 0.015)
    interest_rate = fdp.ConsumeFloatInRange(0.0001, 0.1000)

    try:
        # Provide identically derived integers to both the NG and Legacy implementations
        ng_val = ng_calc_bond(
            utxo_value=amount,
            confirmation_time=confirm_time,
            locktime=locktime,
            current_time=current_time,
            interest_rate=interest_rate,
        )

        legacy_val = legacy_calc_bond(
            value=amount,
            confirm_time=float(confirm_time),
            locktime=float(locktime),
            current_time=float(current_time),
            interest_rate=interest_rate,
        )

        if ng_val != legacy_val:
            raise AssertionError(
                f"Fidelity Bond Computation Mismatched!\n"
                f"NG returned: {ng_val}\n"
                f"Legacy returned: {legacy_val}\n"
                f"Params -> Amt: {amount}, Lock: {locktime}, Confirm: {confirm_time}"
            )

    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pass


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
