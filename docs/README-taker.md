# JoinMarket Taker Client

Mix your bitcoin for privacy via CoinJoin. Takers initiate transactions and pay small fees to makers.

## Installation

Install JoinMarket-NG with the taker component:

```bash
curl -sSL https://raw.githubusercontent.com/joinmarket-ng/joinmarket-ng/main/install.sh | bash -s -- --taker
```

See [Installation](install.md) for backend setup, Tor configuration, and manual install.

## Quick Start

### 1) Create a wallet

```bash
jm-wallet generate --output ~/.joinmarket-ng/wallets/default.mnemonic
```

Store the mnemonic offline. See [Wallet guide](README-jmwallet.md).

### 2) Fund and inspect

```bash
jm-wallet info --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic --backend neutrino
```

### 3) Run a CoinJoin

```bash
jm-taker coinjoin \
  --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic \
  --amount 1000000
```

Default destination is `INTERNAL` (next mixdepth), which is the standard privacy-preserving path.

## Common Use Cases

```bash
# Mix to next mixdepth (INTERNAL)
jm-taker coinjoin --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic --amount 500000

# Mix and send to external destination
jm-taker coinjoin --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic \
  --amount 500000 --destination bc1qexampleaddress...

# Sweep one mixdepth
jm-taker coinjoin --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic \
  --amount 0 --mixdepth 2

# Pick the inputs by hand (interactive TUI)
jm-taker coinjoin --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic \
  --amount 500000 --select-utxos

# Spend an exact input set (repeat --input-utxo as needed)
jm-taker coinjoin --mnemonic-file ~/.joinmarket-ng/wallets/default.mnemonic \
  --amount 500000 --mixdepth 2 \
  --input-utxo TXID:0 --input-utxo OTHER_TXID:1
```

Increase counterparties (for larger anonymity sets) with `--counterparties`.

With `--select-utxos` the selector shows every UTXO in the wallet grouped by
mixdepth. A CoinJoin spends from a single mixdepth, so the first UTXO you
toggle pins the source mixdepth (deselect everything to unpin); pass
`--mixdepth` to pin it up front. The `INTERNAL` destination then targets the
mixdepth after the derived one.

With `--input-utxo`, every listed outpoint must be an eligible input in the
requested mixdepth (mixdepth 0 by default). Fixed-amount CoinJoins and sweeps
spend exactly the listed inputs. If maker or mining fees make that set
insufficient, the round fails instead of adding another wallet UTXO.

## Tumbler

For multi-step automated mixing, create and run a persisted plan with
`jm-tumbler plan` and `jm-tumbler run`.

- Plan format and operational guidance are in [JoinMarket Tumbler](README-tumbler.md).
- Privacy model and protocol-level behavior are in [Technical Privacy Notes](technical/privacy.md).

## Configuration Notes

Configuration merges as: `config.toml` < environment variables < CLI flags.

Backend setup and defaults: [Installation](install.md#configure-backend).

`taker.tx_fee_factor` controls additive fee randomization, not a direct multiplier. A value
of `0.2` picks a session fee rate between the base rate and `base_rate * 1.2`; `0` disables
randomization.

By default, `taker.round_up_cj_fees = true` rounds every selected maker's fee up to the
closest public quantum of the same type. Older makers that exact-match their expected change
can reject the resulting transaction; use `--no-round-up-cj-fees` while interacting with
those makers. `taker.require_quantized_cj_fees` only selects offers already on that grid and
is independent of rounding. The recommended future policy is
`require_quantized_cj_fees = true` with `round_up_cj_fees = false`; it is intended to become
the default.

`taker.counterparty_count` is the per-round target. During fill and authentication, the taker
uses up to `taker.max_maker_replacement_attempts` (default `3`) to restore that target after a
maker fails. `taker.minimum_makers` is only the final floor after those attempts are exhausted
or no candidates remain; a round below that floor fails.

The initial maker and fee preview expires after
`taker.initial_confirmation_timeout_sec` seconds (default `300`). An expired preview is
cancelled before the taker creates a PoDLE commitment or contacts makers; start a fresh run to
fetch current offers. Set the value to `0` only when an unbounded confirmation wait is required.

For all option details, use the auto-generated `jm-taker coinjoin --help` below. Tumbler
commands are documented in [JoinMarket Tumbler](README-tumbler.md).

## Ignored makers

The taker keeps a persisted list of makers that previously misbehaved (rejected
PoDLE commitments, returned an invalid signature, etc.) at
`<data-dir>/ignored_makers.txt`. This list is treated as a **soft preference**:
the maker selector tries to avoid these nicks, but if the resulting eligible
pool is too small to fill the requested counterparty count the selector tops
the pick up from the ignored list rather than failing the whole CoinJoin. Use
`jm-taker clear-ignored-makers` to reset the list.

In contrast, makers that explicitly reject the *current* CoinJoin attempt
(e.g. a fresh blacklist response in this fill phase) are hard-excluded from
that attempt only — they will be retried in future runs unless they also end
up on the persisted ignored list.

## Docker Deployment

This component ships with `docker-compose.yml` for containerized operation.

Typical flow:

```bash
docker-compose up -d bitcoind tor
docker-compose run --rm taker jm-taker coinjoin --amount 1000000
docker-compose logs -f taker
```

Takers only require Tor SOCKS; no Tor control port is needed.

## Command Reference

<!-- AUTO-GENERATED HELP START: jm-taker -->

<details>
<summary><code>jm-taker --help</code></summary>

```

 Usage: jm-taker [OPTIONS] COMMAND [ARGS]...

 JoinMarket Taker - Execute CoinJoin transactions

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help                        Show this message and exit.                    │
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ clear-ignored-makers  Clear the list of ignored makers.                      │
│ coinjoin              Execute a single CoinJoin transaction.                 │
│ config-init           Initialize the config file with default settings.      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

</details>

<details>
<summary><code>jm-taker clear-ignored-makers --help</code></summary>

```

 Usage: jm-taker clear-ignored-makers [OPTIONS]

 Clear the list of ignored makers.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --config-file          PATH  Config file path (decoupled from data dir).     │
│                              Defaults to <data-dir>/config.toml              │
│                              [env var: JOINMARKET_CONFIG_FILE]               │
│ --data-dir     -d      PATH  Data directory for JoinMarket files             │
│                              [env var: JOINMARKET_DATA_DIR]                  │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

</details>

<details>
<summary><code>jm-taker coinjoin --help</code></summary>

```

 Usage: jm-taker coinjoin [OPTIONS]

 Execute a single CoinJoin transaction.

 Configuration is loaded from ~/.joinmarket-ng/config.toml (or
 $JOINMARKET_DATA_DIR/config.toml),
 environment variables, and CLI arguments. CLI arguments have the highest
 priority.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --amount         -a                     INTEGER          Amount in sats   │
│                                                             (0 for sweep)    │
│                                                             [required]       │
│    --backend        -b                     TEXT             Backend type:    │
│                                                             descriptor_wall… │
│                                                             | neutrino       │
│    --bitcoin-netw…                         [mainnet|testne  Bitcoin network  │
│                                            t|signet|regtes  for addresses    │
│                                            t]               (defaults to     │
│                                                             --network)       │
│    --block-target                          INTEGER          Target blocks    │
│                                                             for fee          │
│                                                             estimation       │
│                                                             (1-1008). Cannot │
│                                                             be used with     │
│                                                             neutrino.        │
│    --bond-exponent                         FLOAT            Exponent for     │
│                                                             fidelity bond    │
│                                                             value            │
│                                                             calculation      │
│                                                             [env var:        │
│                                                             BOND_VALUE_EXPO… │
│    --bondless-all…                         FLOAT            Fraction of      │
│                                                             allowance slots  │
│                                                             chosen uniformly │
│                                                             from zero-fee    │
│                                                             offers (0.0-1.0) │
│                                                             [env var:        │
│                                                             BONDLESS_MAKERS… │
│    --bondless-zer…      --no-bondless-…                     Restrict         │
│                                                             allowance spots  │
│                                                             to zero-fee      │
│                                                             offers           │
│                                                             [env var:        │
│                                                             BONDLESS_REQUIR… │
│    --config-file                           PATH             Config file path │
│                                                             (decoupled from  │
│                                                             data dir).       │
│                                                             Defaults to      │
│                                                             <data-dir>/conf… │
│                                                             [env var:        │
│                                                             JOINMARKET_CONF… │
│    --counterparti…  -n                     INTEGER          Number of makers │
│    --data-dir                              PATH             Data directory   │
│                                                             (default:        │
│                                                             ~/.joinmarket-ng │
│                                                             or               │
│                                                             $JOINMARKET_DAT… │
│                                                             [env var:        │
│                                                             JOINMARKET_DATA… │
│    --destination    -d                     TEXT             Destination      │
│                                                             address (or      │
│                                                             'INTERNAL' for   │
│                                                             next mixdepth)   │
│                                                             [default:        │
│                                                             INTERNAL]        │
│    --directory      -D                     TEXT             Directory        │
│                                                             servers          │
│                                                             (comma-separate… │
│                                                             [env var:        │
│                                                             DIRECTORY_SERVE… │
│    --fee-rate                              FLOAT            Manual fee rate  │
│                                                             in sat/vB.       │
│                                                             Mutually         │
│                                                             exclusive with   │
│                                                             --block-target.  │
│    --help                                                   Show this        │
│                                                             message and      │
│                                                             exit.            │
│    --input-utxo                            TEXT             Explicit input   │
│                                                             UTXO as          │
│                                                             txid:vout        │
│                                                             (repeatable).    │
│                                                             CoinJoin spends  │
│                                                             exactly the      │
│                                                             given UTXOs,     │
│                                                             including for    │
│                                                             sweeps, and      │
│                                                             never adds other │
│                                                             inputs. Every    │
│                                                             UTXO must be     │
│                                                             eligible and     │
│                                                             belong to        │
│                                                             --mixdepth.      │
│                                                             Mutually         │
│                                                             exclusive with   │
│                                                             --select-utxos.  │
│    --log-level      -l                     TEXT             Log level        │
│    --max-abs-fee                           INTEGER          Max absolute fee │
│                                                             in sats          │
│    --max-rel-fee                           TEXT             Max relative fee │
│                                                             (0.001=0.1%)     │
│    --mixdepth       -m                     INTEGER          Source mixdepth  │
│                                                             (default 0; with │
│                                                             --select-utxos,  │
│                                                             derived from the │
│                                                             selection unless │
│                                                             set explicitly;  │
│                                                             --input-utxo     │
│                                                             entries must     │
│                                                             belong to this   │
│                                                             mixdepth)        │
│    --mnemonic-file  -f                     PATH             Path to mnemonic │
│                                                             file             │
│    --network                               [mainnet|testne  Protocol network │
│                                            t|signet|regtes  for handshakes   │
│                                            t]                                │
│    --neutrino-url                          TEXT             Neutrino REST    │
│                                                             API URL          │
│                                                             [env var:        │
│                                                             NEUTRINO_URL]    │
│    --prompt-bip39…                                          Prompt for BIP39 │
│                                                             passphrase       │
│                                                             interactively    │
│    --quantized-of…      --allow-non-qu…                     Only select      │
│                                                             offers whose     │
│                                                             advertised       │
│                                                             CoinJoin fee is  │
│                                                             on the public    │
│                                                             grid             │
│    --round-up-cj-…      --no-round-up-…                     Round selected   │
│                                                             maker fees up to │
│                                                             public fee       │
│                                                             quanta           │
│    --rpc-url                               TEXT             Bitcoin full     │
│                                                             node RPC URL     │
│                                                             [env var:        │
│                                                             BITCOIN_RPC_URL] │
│    --select-utxos   -s                                      Interactively    │
│                                                             select UTXOs     │
│                                                             (fzf-like TUI)   │
│    --tor-socks-ho…                         TEXT             Tor SOCKS proxy  │
│                                                             host (overrides  │
│                                                             TOR__SOCKS_HOST) │
│    --tor-socks-po…                         INTEGER          Tor SOCKS proxy  │
│                                                             port (overrides  │
│                                                             TOR__SOCKS_PORT) │
│    --yes            -y                                      Skip             │
│                                                             confirmation     │
│                                                             prompt           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

</details>

<details>
<summary><code>jm-taker config-init --help</code></summary>

```

 Usage: jm-taker config-init [OPTIONS]

 Initialize the config file with default settings.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --config-file          PATH  Config file path (decoupled from data dir).     │
│                              Defaults to <data-dir>/config.toml              │
│                              [env var: JOINMARKET_CONFIG_FILE]               │
│ --data-dir     -d      PATH  Data directory for JoinMarket files             │
│                              [env var: JOINMARKET_DATA_DIR]                  │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

</details>


<!-- AUTO-GENERATED HELP END: jm-taker -->
