"""Strict BIP174 PSBT v0 parsing and record-preserving updates."""

from __future__ import annotations

from dataclasses import dataclass, field

from jmcore.bitcoin import ParsedTransaction, encode_varint, parse_transaction_bytes

PSBT_MAGIC = b"psbt\xff"

# Global key types.
PSBT_GLOBAL_UNSIGNED_TX = 0x00
PSBT_GLOBAL_XPUB = 0x01
PSBT_GLOBAL_VERSION = 0xFB

# Input key types.
PSBT_IN_NON_WITNESS_UTXO = 0x00
PSBT_IN_WITNESS_UTXO = 0x01
PSBT_IN_PARTIAL_SIG = 0x02
PSBT_IN_SIGHASH_TYPE = 0x03
PSBT_IN_REDEEM_SCRIPT = 0x04
PSBT_IN_WITNESS_SCRIPT = 0x05
PSBT_IN_BIP32_DERIVATION = 0x06
PSBT_IN_FINAL_SCRIPTSIG = 0x07
PSBT_IN_FINAL_SCRIPTWITNESS = 0x08
PSBT_IN_PROPRIETARY = 0xFC

# Output key types.
PSBT_OUT_REDEEM_SCRIPT = 0x00
PSBT_OUT_WITNESS_SCRIPT = 0x01
PSBT_OUT_BIP32_DERIVATION = 0x02
PSBT_OUT_PROPRIETARY = 0xFC


class PSBTError(ValueError):
    """Raised when a PSBT violates BIP174 serialization requirements."""


@dataclass(frozen=True)
class PSBTKeyValue:
    """An ordered raw PSBT key/value record."""

    key: bytes
    value: bytes


@dataclass
class PSBTMap:
    """A PSBT map retaining record order and unknown records."""

    records: list[PSBTKeyValue] = field(default_factory=list)

    def append(self, key: bytes, value: bytes) -> None:
        """Append a unique, nonempty raw record to this map."""
        if not key:
            raise PSBTError("PSBT map keys must not be empty")
        if any(record.key == key for record in self.records):
            raise PSBTError(f"Duplicate PSBT key: {key.hex()}")
        self.records.append(PSBTKeyValue(key=key, value=value))

    def serialize(self) -> bytes:
        """Serialize this map with canonical CompactSize lengths."""
        result = bytearray()
        for record in self.records:
            result.extend(encode_varint(len(record.key)))
            result.extend(record.key)
            result.extend(encode_varint(len(record.value)))
            result.extend(record.value)
        result.append(0)
        return bytes(result)


@dataclass(frozen=True)
class WitnessUTXO:
    """The amount and scriptPubKey contained in a PSBT witness UTXO record."""

    value: int
    script_pubkey: bytes


@dataclass(frozen=True)
class BIP32KeyOrigin:
    """A BIP32 public key and its master fingerprint and derivation path."""

    pubkey: bytes
    fingerprint: bytes
    path: tuple[int, ...]


@dataclass
class ParsedPSBT:
    """A parsed BIP174 PSBT v0, retaining all raw map records."""

    unsigned_tx: bytes
    transaction: ParsedTransaction
    global_map: PSBTMap
    input_maps: list[PSBTMap]
    output_maps: list[PSBTMap]

    def serialize(self) -> bytes:
        """Serialize the PSBT while preserving all map record order."""
        result = bytearray(PSBT_MAGIC)
        result.extend(self.global_map.serialize())
        for input_map in self.input_maps:
            result.extend(input_map.serialize())
        for output_map in self.output_maps:
            result.extend(output_map.serialize())
        return bytes(result)

    def append_input_key_value(self, input_index: int, key: bytes, value: bytes) -> None:
        """Append a valid unique record to an input map."""
        if input_index < 0:
            raise PSBTError(f"PSBT input index out of range: {input_index}")
        try:
            input_map = self.input_maps[input_index]
        except IndexError as error:
            raise PSBTError(f"PSBT input index out of range: {input_index}") from error
        _validate_key("input", key)
        _validate_map_records("input", PSBTMap(records=[PSBTKeyValue(key=key, value=value)]))
        input_map.append(key, value)


def parse_psbt(data: bytes) -> ParsedPSBT:
    """Parse a strict, complete BIP174 PSBT v0 binary payload."""
    if not data.startswith(PSBT_MAGIC):
        raise PSBTError("Invalid PSBT magic bytes")

    offset = len(PSBT_MAGIC)
    global_map, offset = _read_map(data, offset, "global")
    _validate_map_records("global", global_map)
    unsigned_tx = _get_unsigned_transaction(global_map)
    _validate_version(global_map)

    try:
        transaction = parse_transaction_bytes(unsigned_tx)
    except Exception as error:
        raise PSBTError(f"Invalid PSBT unsigned transaction: {error}") from error
    if transaction.has_witness:
        raise PSBTError("PSBT unsigned transaction must not contain witness data")
    if any(tx_input.scriptsig for tx_input in transaction.inputs):
        raise PSBTError("PSBT unsigned transaction must have empty scriptSigs")

    input_maps, offset = _read_expected_maps(data, offset, len(transaction.inputs), "input")
    output_maps, offset = _read_expected_maps(data, offset, len(transaction.outputs), "output")
    for input_map in input_maps:
        _validate_map_records("input", input_map)
    for output_map in output_maps:
        _validate_map_records("output", output_map)
    if offset != len(data):
        raise PSBTError("Trailing data after PSBT maps")

    return ParsedPSBT(
        unsigned_tx=unsigned_tx,
        transaction=transaction,
        global_map=global_map,
        input_maps=input_maps,
        output_maps=output_maps,
    )


def parse_witness_utxo(value: bytes) -> WitnessUTXO:
    """Parse a BIP174 witness UTXO value with exact consumption."""
    if len(value) < 8:
        raise PSBTError("Truncated witness UTXO value")
    amount = int.from_bytes(value[:8], "little", signed=False)
    script_length, offset = _read_compact_size(value, 8, "witness UTXO script length")
    remaining = len(value) - offset
    if script_length > remaining:
        raise PSBTError("Truncated witness UTXO scriptPubKey")
    if script_length != remaining:
        raise PSBTError("Trailing data after witness UTXO scriptPubKey")
    return WitnessUTXO(value=amount, script_pubkey=value[offset:])


def parse_bip32_derivation(key: bytes, value: bytes) -> BIP32KeyOrigin:
    """Parse a BIP174 BIP32 derivation key/value pair."""
    if len(key) != 34:
        raise PSBTError("BIP32 derivation key must contain a type byte and 33-byte public key")
    pubkey = key[1:]
    if pubkey[0] not in (0x02, 0x03):
        raise PSBTError("BIP32 derivation key must contain a compressed public key")
    _validate_key_origin_value(value, "BIP32 derivation")
    path = tuple(
        int.from_bytes(value[offset : offset + 4], "little", signed=False)
        for offset in range(4, len(value), 4)
    )
    return BIP32KeyOrigin(pubkey=pubkey, fingerprint=value[:4], path=path)


def _read_expected_maps(
    data: bytes, offset: int, count: int, map_kind: str
) -> tuple[list[PSBTMap], int]:
    maps: list[PSBTMap] = []
    for index in range(count):
        if offset == len(data):
            raise PSBTError(f"Truncated PSBT: missing {map_kind} map {index}")
        parsed_map, offset = _read_map(data, offset, map_kind)
        maps.append(parsed_map)
    return maps, offset


def _read_map(data: bytes, offset: int, map_kind: str) -> tuple[PSBTMap, int]:
    parsed_map = PSBTMap()
    while True:
        key_length, offset = _read_compact_size(data, offset, f"{map_kind} map key length")
        if key_length == 0:
            return parsed_map, offset
        key, offset = _read_bytes(data, offset, key_length, f"{map_kind} map key")
        _validate_key(map_kind, key)
        value_length, offset = _read_compact_size(data, offset, f"{map_kind} map value length")
        value, offset = _read_bytes(data, offset, value_length, f"{map_kind} map value")
        parsed_map.append(key, value)


def _read_compact_size(data: bytes, offset: int, context: str) -> tuple[int, int]:
    if offset >= len(data):
        raise PSBTError(f"Truncated {context}")
    first = data[offset]
    offset += 1
    if first < 0xFD:
        return first, offset
    length = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    encoded, offset = _read_bytes(data, offset, length, context)
    value = int.from_bytes(encoded, "little", signed=False)
    minimum = {0xFD: 0xFD, 0xFE: 0x10000, 0xFF: 0x100000000}[first]
    if value < minimum:
        raise PSBTError(f"Noncanonical CompactSize for {context}")
    return value, offset


def _read_bytes(data: bytes, offset: int, length: int, context: str) -> tuple[bytes, int]:
    if length > len(data) - offset:
        raise PSBTError(f"Truncated {context}")
    return data[offset : offset + length], offset + length


def _get_unsigned_transaction(global_map: PSBTMap) -> bytes:
    matching = [record for record in global_map.records if record.key == b"\x00"]
    if not matching:
        raise PSBTError("PSBT global map is missing the unsigned transaction")
    if len(matching) != 1:
        raise PSBTError("PSBT global map has multiple unsigned transactions")
    return matching[0].value


def _validate_version(global_map: PSBTMap) -> None:
    versions = [
        record for record in global_map.records if record.key == bytes([PSBT_GLOBAL_VERSION])
    ]
    if not versions:
        return
    if len(versions) != 1:
        raise PSBTError("PSBT global map has multiple version records")
    version = versions[0].value
    if len(version) != 4:
        raise PSBTError("PSBT version must be a 4-byte uint32")
    if int.from_bytes(version, "little", signed=False) != 0:
        raise PSBTError("Only PSBT version 0 is supported")


def _validate_key(map_kind: str, key: bytes) -> None:
    if not key:
        raise PSBTError("PSBT map keys must not be empty")
    key_type = key[0]
    singleton_types = {
        "global": {PSBT_GLOBAL_UNSIGNED_TX, PSBT_GLOBAL_VERSION},
        "input": {
            PSBT_IN_NON_WITNESS_UTXO,
            PSBT_IN_WITNESS_UTXO,
            PSBT_IN_SIGHASH_TYPE,
            PSBT_IN_REDEEM_SCRIPT,
            PSBT_IN_WITNESS_SCRIPT,
            PSBT_IN_FINAL_SCRIPTSIG,
            PSBT_IN_FINAL_SCRIPTWITNESS,
            0x09,
        },
        "output": {PSBT_OUT_REDEEM_SCRIPT, PSBT_OUT_WITNESS_SCRIPT},
    }
    if key_type in singleton_types[map_kind] and len(key) != 1:
        raise PSBTError(f"PSBT {map_kind} singleton key type {key_type:#x} must not carry key data")

    if map_kind == "global" and key_type == PSBT_GLOBAL_XPUB and len(key) != 79:
        raise PSBTError("PSBT global xpub key must contain a 78-byte extended public key")
    keyed_pubkey_types = {
        "global": set(),
        "input": {PSBT_IN_PARTIAL_SIG, PSBT_IN_BIP32_DERIVATION},
        "output": {PSBT_OUT_BIP32_DERIVATION},
    }
    if key_type in keyed_pubkey_types[map_kind]:
        if len(key) != 34 or key[1] not in (0x02, 0x03):
            raise PSBTError(
                f"PSBT {map_kind} key type {key_type:#x} must contain a compressed public key"
            )


def _validate_map_records(map_kind: str, psbt_map: PSBTMap) -> None:
    for record in psbt_map.records:
        key_type = record.key[0]
        if map_kind == "global" and key_type == PSBT_GLOBAL_XPUB:
            _validate_key_origin_value(record.value, "global xpub")
        elif map_kind == "input":
            if key_type == PSBT_IN_WITNESS_UTXO:
                parse_witness_utxo(record.value)
            elif key_type == PSBT_IN_SIGHASH_TYPE and len(record.value) != 4:
                raise PSBTError("PSBT input sighash type must be a 4-byte uint32")
            elif key_type == PSBT_IN_PARTIAL_SIG and not record.value:
                raise PSBTError("PSBT input partial signature must not be empty")
            elif key_type == PSBT_IN_BIP32_DERIVATION:
                parse_bip32_derivation(record.key, record.value)
        elif map_kind == "output" and key_type == PSBT_OUT_BIP32_DERIVATION:
            parse_bip32_derivation(record.key, record.value)


def _validate_key_origin_value(value: bytes, context: str) -> None:
    if len(value) < 4 or (len(value) - 4) % 4 != 0:
        raise PSBTError(f"PSBT {context} must contain a fingerprint and uint32 path")
