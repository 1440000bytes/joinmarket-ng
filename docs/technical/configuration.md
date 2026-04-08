# Configuration

JoinMarket NG loads settings in this order (highest priority first):

1. CLI arguments
2. Environment variables
3. `~/.joinmarket-ng/config.toml`
4. Built-in defaults

## Config File

Main config path:

- `~/.joinmarket-ng/config.toml`

Template/reference:

- `config.toml.template`

The installer creates a starter config automatically.

## Section Names

Top-level sections in config use these names:

- `[tor]`
- `[bitcoin]`
- `[network_config]`
- `[wallet]`
- `[logging]`
- `[notifications]`
- `[maker]`
- `[taker]`
- `[directory_server]`
- `[orderbook_watcher]`

## Environment Variable Mapping

Nested fields use double underscores:

- `TOR__SOCKS_HOST`
- `BITCOIN__RPC_URL`
- `NETWORK_CONFIG__NETWORK`
- `MAKER__MIN_SIZE`
- `TAKER__COUNTERPARTY_COUNT`

Some CLI flags still support legacy env var names (for compatibility), but config/env should prefer the canonical section-based names above.

## Minimal Example

```toml
[bitcoin]
backend_type = "descriptor_wallet"
rpc_url = "http://127.0.0.1:8332"
rpc_user = "rpcuser"
rpc_password = "rpcpassword"

[network_config]
network = "mainnet"

[tor]
socks_host = "127.0.0.1"
socks_port = 9050
```

## Backend Options

- `descriptor_wallet` (recommended)
- `scantxoutset`
- `neutrino`

## Directory Server Heartbeat Settings

The `[directory_server]` section supports heartbeat liveness controls:

- `heartbeat_sweep_interval` (default `60.0`): seconds between sweep cycles
- `heartbeat_idle_threshold` (default `600.0`): idle seconds before probing
- `heartbeat_hard_evict` (default `1500.0`): idle seconds before unconditional eviction
- `heartbeat_pong_wait` (default `30.0`): seconds to wait for PONG reply

These values are tuned to match joinmarket-rs defaults for interoperability.

## Notes

- BIP39 passphrases are not intended to be stored in config for normal operations.
- Keep secrets out of shell history; prefer config file permissions and environment handling best practices.
