# ruff: noqa: E402
from jmcore.bitcoin import derive_address_bip86, mnemonic_to_seed

mnemonic = (
    "burden notable love elephant orbit couch message galaxy elevator exile drop toilet"
)
seed = mnemonic_to_seed(mnemonic)
# Taker P2TR (BIP86) address at mixdepth 0, branch 0, index 0
# Path: m/86'/1'/0'/0/0 for regtest/testnet
path = "m/86'/1'/0'/0/0"
addr = derive_address_bip86(seed, path, network="regtest")
print(f"TAKER_P2TR_ADDR: {addr}")

# Maker Segwit (BIP84) address at mixdepth 0, branch 0, index 0
from jmcore.bitcoin import derive_address_bip84

# Maker1 mnemonic
m_mnemonic = (
    "avoid whisper mesh corn already blur sudden fine planet chicken hover sniff"
)
m_seed = mnemonic_to_seed(m_mnemonic)
m_addr = derive_address_bip84(m_seed, "m/84'/1'/0'/0/0", network="regtest")
print(f"MAKER_SEGWIT_ADDR: {m_addr}")
