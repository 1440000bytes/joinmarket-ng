# ruff: noqa: E402
import os
import struct


def write_seed(name, data):
    with open(f"fuzz/corpus/tx_parser/{name}.bin", "wb") as f:
        f.write(data)


def encode_varint(i):
    if i < 0xFD:
        return struct.pack("<B", i)
    elif i <= 0xFFFF:
        return struct.pack("<BH", 0xFD, i)
    elif i <= 0xFFFFFFFF:
        return struct.pack("<BI", 0xFE, i)
    else:
        return struct.pack("<BQ", 0xFF, i)


def create_complex_tx(num_inputs, num_outputs, witness_items_per_input):
    # Version 2
    tx = struct.pack("<I", 2)
    # SegWit Marker & Flag
    tx += b"\x00\x01"

    # Inputs
    tx += encode_varint(num_inputs)
    for i in range(num_inputs):
        tx += b"\x00" * 32  # txid
        tx += struct.pack("<I", i)  # vout
        tx += b"\x00"  # scriptSig (empty for SegWit)
        tx += b"\xff\xff\xff\xff"  # sequence

    # Outputs
    tx += encode_varint(num_outputs)
    for i in range(num_outputs):
        tx += struct.pack("<q", 1000 + i)  # value
        tx += b"\x16\x00\x14" + (b"\x11" * 20)  # P2WPKH scriptpubkey (22 bytes)

    # Witnesses
    for i in range(num_inputs):
        tx += encode_varint(witness_items_per_input)
        for j in range(witness_items_per_input):
            item = b"witness" * (j + 1)
            tx += encode_varint(len(item))
            tx += item

    # Locktime
    tx += struct.pack("<I", 500000)
    return tx


os.makedirs("fuzz/corpus/tx_parser", exist_ok=True)

# 1. Deep Witness Stack (15 items per input)
write_seed("deep_witness", create_complex_tx(2, 2, 15))

# 2. Large Number of Outputs (100 outputs)
write_seed("many_outputs", create_complex_tx(1, 100, 2))

# 3. Maximum Possible Value (MAX_MONEY - 1)
MAX_MONEY = 2100000000000000
tx_max_val = create_complex_tx(1, 1, 2)
# Replace the value of the first output (at offset: 4 + 2 + (1*32 + 4 + 1 + 4) + 1)
# Offset calculation: 4 (ver) + 2 (segwit) + 1 (in_count) + (32+4+1+4) (input 0) + 1 (out_count) = 53
tx_max_val = bytearray(tx_max_val)
tx_max_val[53:61] = struct.pack("<q", MAX_MONEY - 1)
write_seed("max_money_minus_one", bytes(tx_max_val))

# 4. Large Number of Inputs (50 inputs)
write_seed("many_inputs", create_complex_tx(50, 1, 2))

print("Edge-case seeds generated successfully.")
