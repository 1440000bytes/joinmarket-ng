"""Validation for SeedSigner BIP46 fidelity-bond registration payloads."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bitcointx.core.key import CPubKey
from jmcore.btc_script import mk_freeze_script
from jmcore.timenumber import timenumber_to_timestamp

from jmwallet.wallet.address import script_to_p2wsh_address

_EXPECTED_FIELDS = (
    "type",
    "version",
    "network",
    "master_fingerprint",
    "derivation_path",
    "index",
    "locktime",
    "locktime_date",
    "pubkey",
    "address",
)
_VALID_NETWORKS = {"mainnet", "testnet", "signet", "regtest"}
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{8}\Z")
_PUBKEY_RE = re.compile(r"(?:02|03)[0-9a-f]{64}\Z")
_LOCKTIME_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}\Z")


class BondRegistrationError(ValueError):
    """Raised when a SeedSigner BIP46 registration payload is invalid."""


@dataclass(frozen=True)
class SeedSignerBondRegistration:
    """A validated SeedSigner BIP46 registration and its reconstructed script."""

    network: str
    master_fingerprint: str
    derivation_path: str
    index: int
    locktime: int
    locktime_date: str
    pubkey: str
    address: str
    witness_script: bytes


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise BondRegistrationError(f"Duplicate JSON field: {key}")
        payload[key] = value
    return payload


def _require_string(payload: dict[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise BondRegistrationError(f"{field} must be a string")
    return value


def _require_integer(payload: dict[str, Any], field: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise BondRegistrationError(f"{field} must be an integer")
    return value


def parse_bip46_registration_payload(payload_text: str) -> SeedSignerBondRegistration:
    """Parse and independently verify a canonical SeedSigner BIP46 payload.

    The payload is a trust boundary. Its compact ASCII encoding, schema, key
    order, timenumber derivation, public key, and P2WSH address are all checked
    before callers can persist any of its values.
    """
    try:
        payload_text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BondRegistrationError("Payload must contain only ASCII characters") from exc

    try:
        payload = json.loads(payload_text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise BondRegistrationError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise BondRegistrationError("Payload must be a JSON object")

    payload_keys = tuple(payload)
    unknown_fields = set(payload) - set(_EXPECTED_FIELDS)
    if unknown_fields:
        raise BondRegistrationError(f"Unknown JSON field(s): {', '.join(sorted(unknown_fields))}")
    missing_fields = set(_EXPECTED_FIELDS) - set(payload)
    if missing_fields:
        raise BondRegistrationError(f"Missing JSON field(s): {', '.join(sorted(missing_fields))}")
    if payload_keys != _EXPECTED_FIELDS:
        raise BondRegistrationError("JSON fields are not in the required canonical order")

    if _require_string(payload, "type") != "seedsigner-bip46":
        raise BondRegistrationError("type must be 'seedsigner-bip46'")
    if _require_integer(payload, "version") != 1:
        raise BondRegistrationError("version must be 1")

    network = _require_string(payload, "network")
    if network not in _VALID_NETWORKS:
        raise BondRegistrationError("network must be mainnet, testnet, signet, or regtest")

    master_fingerprint = _require_string(payload, "master_fingerprint")
    if _FINGERPRINT_RE.fullmatch(master_fingerprint) is None:
        raise BondRegistrationError("master_fingerprint must be 8 lowercase hexadecimal characters")

    index = _require_integer(payload, "index")
    if not 0 <= index <= 959:
        raise BondRegistrationError("index must be between 0 and 959")

    locktime = _require_integer(payload, "locktime")
    expected_locktime = timenumber_to_timestamp(index)
    if locktime != expected_locktime:
        raise BondRegistrationError("locktime does not match the index timenumber")

    locktime_date = _require_string(payload, "locktime_date")
    if _LOCKTIME_DATE_RE.fullmatch(locktime_date) is None:
        raise BondRegistrationError("locktime_date must use strict YYYY-MM format")
    expected_locktime_date = datetime.fromtimestamp(locktime, tz=UTC).strftime("%Y-%m")
    if locktime_date != expected_locktime_date:
        raise BondRegistrationError("locktime_date does not match locktime")

    coin_type = 0 if network == "mainnet" else 1
    derivation_path = _require_string(payload, "derivation_path")
    expected_path = f"m/84'/{coin_type}'/0'/2/{index}"
    if derivation_path != expected_path:
        raise BondRegistrationError("derivation_path does not match network and index")

    pubkey = _require_string(payload, "pubkey")
    if _PUBKEY_RE.fullmatch(pubkey) is None:
        raise BondRegistrationError("pubkey must be a lowercase compressed 33-byte hexadecimal key")
    pubkey_bytes = bytes.fromhex(pubkey)
    if not CPubKey(pubkey_bytes).is_fullyvalid():
        raise BondRegistrationError("pubkey is not a valid secp256k1 public key")

    address = _require_string(payload, "address")
    witness_script = mk_freeze_script(pubkey, locktime)
    expected_address = script_to_p2wsh_address(witness_script, network)
    if address != expected_address:
        raise BondRegistrationError("address does not match the reconstructed P2WSH witness script")

    canonical_payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    if payload_text != canonical_payload:
        raise BondRegistrationError("Payload must use canonical compact ASCII JSON encoding")

    return SeedSignerBondRegistration(
        network=network,
        master_fingerprint=master_fingerprint,
        derivation_path=derivation_path,
        index=index,
        locktime=locktime,
        locktime_date=locktime_date,
        pubkey=pubkey,
        address=address,
        witness_script=witness_script,
    )
