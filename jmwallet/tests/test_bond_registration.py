"""Tests for SeedSigner BIP46 fidelity-bond registration validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from jmwallet.wallet.bond_registration import (
    BondRegistrationError,
    parse_bip46_registration_payload,
)

SEEDSIGNER_PUBKEY = "03ec8067418537bbb52d5d3e64e2868e67635c33cfeadeb9a46199f89ebfaab226"
SEEDSIGNER_VECTOR: dict[str, object] = {
    "type": "seedsigner-bip46",
    "version": 1,
    "network": "mainnet",
    "master_fingerprint": "73c5da0a",
    "derivation_path": "m/84'/0'/0'/2/240",
    "index": 240,
    "locktime": 2208988800,
    "locktime_date": "2040-01",
    "pubkey": SEEDSIGNER_PUBKEY,
    "address": "bc1qul0q45njptsadnymdtv34at7karyva3v7k2vj8qc7m2702rnvddq0z20u5",
}


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _mutated(**changes: Any) -> str:
    payload = SEEDSIGNER_VECTOR.copy()
    payload.update(changes)
    return _canonical(payload)


def test_parse_seedsigner_vector_reconstructs_bond() -> None:
    registration = parse_bip46_registration_payload(_canonical(SEEDSIGNER_VECTOR))

    assert registration.network == "mainnet"
    assert registration.master_fingerprint == "73c5da0a"
    assert registration.derivation_path == "m/84'/0'/0'/2/240"
    assert registration.index == 240
    assert registration.locktime == 2208988800
    assert registration.locktime_date == "2040-01"
    assert registration.pubkey == SEEDSIGNER_VECTOR["pubkey"]
    assert registration.address == SEEDSIGNER_VECTOR["address"]
    assert registration.witness_script.hex() == (
        "05807eaa8300b1752103ec8067418537bbb52d5d3e64e2868e67635c33cfeadeb9a46199f89ebfaab226ac"
    )


def test_parse_signet_vector_uses_test_family_coin_type_and_address() -> None:
    payload = SEEDSIGNER_VECTOR | {
        "network": "signet",
        "derivation_path": "m/84'/1'/0'/2/240",
        "pubkey": "020bb71ecf99ab2289d16dc0b8b1cb4c51699db38a215bbb212d1a2b30d07b8806",
        "address": "tb1qnkuzv3jckcxd9xdnvse36x2m6ylcg4aqgam2gd4tt689k44ft6eq526xlk",
    }

    registration = parse_bip46_registration_payload(_canonical(payload))

    assert registration.network == "signet"
    assert registration.derivation_path == "m/84'/1'/0'/2/240"
    assert registration.address == payload["address"]


def test_parser_rejects_invalid_compressed_curve_point() -> None:
    with pytest.raises(BondRegistrationError, match="secp256k1"):
        parse_bip46_registration_payload(_mutated(pubkey="03" + "11" * 32))


@pytest.mark.parametrize(
    "payload",
    [
        _canonical(SEEDSIGNER_VECTOR) + "\n",
        json.dumps(SEEDSIGNER_VECTOR),
        _canonical({key: SEEDSIGNER_VECTOR[key] for key in reversed(SEEDSIGNER_VECTOR)}),
        _canonical({key: value for key, value in SEEDSIGNER_VECTOR.items() if key != "address"}),
        _canonical({**SEEDSIGNER_VECTOR, "xpub": "xpub661MyMwAqRbcF"}),
        _canonical({**SEEDSIGNER_VECTOR, "pubkey": "xpub661MyMwAqRbcF"}),
        "[]",
        _canonical(SEEDSIGNER_VECTOR)[:-1]
        + ',"address":"bc1qul0q45njptsadnymdtv34at7karyva3v7k2vj8qc7m2702rnvddq0z20u5"}',
    ],
)
def test_parser_rejects_noncanonical_schema_and_legacy_xpub_payloads(payload: str) -> None:
    with pytest.raises(BondRegistrationError):
        parse_bip46_registration_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", 1),
        ("version", True),
        ("network", 1),
        ("master_fingerprint", 1),
        ("derivation_path", 1),
        ("index", True),
        ("locktime", True),
        ("locktime_date", 1),
        ("pubkey", 1),
        ("address", 1),
    ],
)
def test_parser_rejects_wrong_scalar_types(field: str, value: object) -> None:
    with pytest.raises(BondRegistrationError):
        parse_bip46_registration_payload(_mutated(**{field: value}))


@pytest.mark.parametrize(
    "payload_factory",
    [
        lambda: _mutated(type="seedsigner-bip46-v0"),
        lambda: _mutated(version=2),
        lambda: _mutated(network="bitcoin"),
        lambda: _mutated(master_fingerprint="73C5DA0A"),
        lambda: _mutated(derivation_path="m/84'/1'/0'/2/240"),
        lambda: _mutated(index=-1),
        lambda: _mutated(index=960),
        lambda: _mutated(locktime=2208988801),
        lambda: _mutated(locktime_date="2040-1"),
        lambda: _mutated(locktime_date="2040-02"),
        lambda: _mutated(pubkey=SEEDSIGNER_PUBKEY.upper()),
        lambda: _mutated(address="bc1qul0q45njptsadnymdtv34at7karyva3v7k2vj8qc7m2702rnvddq0z20u4"),
    ],
)
def test_parser_rejects_field_mutations(payload_factory: Callable[[], str]) -> None:
    with pytest.raises(BondRegistrationError):
        parse_bip46_registration_payload(payload_factory())
