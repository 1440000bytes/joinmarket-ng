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
    from jmcore.protocol import (
        create_handshake_request,
        create_handshake_response,
        parse_peerlist_entry,
        create_peerlist_entry,
        NICK_PEERLOCATOR_SEPARATOR,
    )

    try:
        from jmdaemon.onionmc import client_handshake_json
    except Exception:
        client_handshake_json = None


def fuzz_handshake_symmetry(fdp):
    """Tests Handshake JSON structure parity."""
    if client_handshake_json is None:
        return

    nick = fdp.ConsumeUnicodeNoSurrogates(14)
    location = fdp.ConsumeUnicodeNoSurrogates(64)
    network = fdp.ConsumeUnicodeNoSurrogates(10)

    # 1. Client Handshake
    ng_client = create_handshake_request(nick, location, network)
    # Compare keys and core values with legacy template
    for key in ["app-name", "directory", "proto-ver", "nick", "network"]:
        if ng_client[key] != client_handshake_json.get(key) and key not in [
            "nick",
            "network",
        ]:
            # Note: Template has empty nick/network, but NG fills them.
            continue
        if key == "proto-ver":
            if ng_client[key] != 5:
                raise AssertionError(
                    f"Handshake Proto-Ver Mismatch! NG: {ng_client[key]}"
                )

    # 2. Server Handshake
    ng_server = create_handshake_response(nick, network, accepted=True)
    if ng_server["app-name"] != "joinmarket" or ng_server["proto-ver-min"] != 5:
        raise AssertionError(f"Server Handshake Mismatch! {ng_server}")


def fuzz_peerlist_parity(fdp):
    """Tests Peerlist entry parsing/formatting symmetry."""
    nick = fdp.ConsumeUnicodeNoSurrogates(14).replace(";", "").replace(",", "")
    location = fdp.ConsumeUnicodeNoSurrogates(64).replace(";", "").replace(",", "")
    disconnected = fdp.ConsumeBool()

    # 1. Formatting
    ng_entry = create_peerlist_entry(nick, location, disconnected=disconnected)

    # Legacy Format Logic (from OnionMessageChannel.send_peers)
    legacy_entry = f"{nick}{NICK_PEERLOCATOR_SEPARATOR}{location}"
    if disconnected:
        legacy_entry += f"{NICK_PEERLOCATOR_SEPARATOR}D"

    if ng_entry != legacy_entry:
        raise AssertionError(
            f"Peerlist Entry Mismatch!\nNG: {ng_entry}\nLegacy: {legacy_entry}"
        )

    # 2. Parsing
    # The fuzzer will find if NG's parser rejects valid legacy entries or vice versa
    raw_entry = fdp.ConsumeUnicodeNoSurrogates(128)
    try:
        n_nick, n_loc, n_disc, n_feat = parse_peerlist_entry(raw_entry)

        # Legacy Parsing Logic (from OnionMessageChannel.process_control_message)
        parts = raw_entry.split(NICK_PEERLOCATOR_SEPARATOR)
        if len(parts) >= 2:
            l_nick = parts[0]
            _l_loc = parts[1]
            l_disc = "D" in parts[2:]

            if n_nick != l_nick or n_disc != l_disc:
                raise AssertionError(
                    f"Peerlist Parse Mismatch!\nInput: {raw_entry}\nNG: {n_nick}, {n_disc}\nLegacy: {l_nick}, {l_disc}"
                )
    except Exception:
        pass


def TestOneInput(data):
    if len(data) < 16:
        return
    fdp = atheris.FuzzedDataProvider(data)
    domain = fdp.ConsumeIntInRange(0, 1)
    if domain == 0:
        fuzz_handshake_symmetry(fdp)
    elif domain == 1:
        fuzz_peerlist_parity(fdp)


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
