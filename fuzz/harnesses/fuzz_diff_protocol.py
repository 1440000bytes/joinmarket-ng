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
    from jmcore.protocol import parse_jm_message, format_jm_message, COMMAND_PREFIX

    # Try to import legacy components
    try:
        from jmdaemon.onionmc import OnionMessageChannel

        # Mocking for legacy OnionMessageChannel
        class MockDaemon:
            def __init__(self):
                self.nick = "mock_nick"

        class MockOnionMessageChannel(OnionMessageChannel):
            def __init__(self):
                self.nick = "sender_nick"
                self.hostid = "onion-network"
                self.btc_network = "mainnet"

        legacy_mc = MockOnionMessageChannel()
    except Exception:
        legacy_mc = None  # type: ignore[assignment]


def fuzz_message_formatting(fdp):
    """Tests !nick!cmd formatting symmetry."""
    if not legacy_mc:
        return

    from_nick = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(1, 14))
    to_nick = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(1, 14))
    cmd = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(1, 10))
    msg = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 100))

    # NG Format
    ng_fmt = format_jm_message(from_nick, to_nick, cmd, msg)

    # Legacy Format (OnionMessageChannel.get_privmsg)
    legacy_fmt = legacy_mc.get_privmsg(to_nick, cmd, msg, source_nick=from_nick)

    if ng_fmt != legacy_fmt:
        raise AssertionError(
            f"Message Formatting Mismatch!\nNG: {ng_fmt}\nLegacy: {legacy_fmt}"
        )


def fuzz_message_parsing(fdp):
    """Tests !nick!cmd parsing symmetry."""
    raw_msg = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 256))

    # NG Parse
    ng_res = parse_jm_message(raw_msg)

    # Legacy Parse (Extracted from OnionMessageChannel.receive_msg)
    try:
        nicks_msgs = raw_msg.split(COMMAND_PREFIX)
        if len(nicks_msgs) < 3:
            legacy_res = None
        else:
            from_nick, to_nick = nicks_msgs[:2]
            # In legacy receive_msg, it then handles the 'msg' part
            rest = COMMAND_PREFIX.join(nicks_msgs[2:])
            legacy_res = (from_nick, to_nick, rest)
    except Exception:
        legacy_res = None

    if ng_res != legacy_res:
        # Note: If NG handles it as None and legacy handles it as something else, or vice-versa
        raise AssertionError(
            f"Message Parsing Mismatch!\nInput: {raw_msg}\nNG: {ng_res}\nLegacy: {legacy_res}"
        )


def TestOneInput(data):
    if len(data) < 16:
        return
    fdp = atheris.FuzzedDataProvider(data)
    domain = fdp.ConsumeIntInRange(0, 1)
    if domain == 0:
        fuzz_message_formatting(fdp)
    elif domain == 1:
        fuzz_message_parsing(fdp)


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
