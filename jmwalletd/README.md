# jmwalletd

A modern, JAM-compatible HTTP/WebSocket API daemon for JoinMarket-NG.

## Overview

`jmwalletd` provides a REST API and WebSocket interface that is fully compatible with the reference JoinMarket implementation's `jmwalletd` component. This allows the [JAM](https://github.com/joinmarket-webui/jam) web interface to work seamlessly with the JoinMarket-NG backend.

## Features

- **JAM Compatibility**: Drop-in replacement for the reference daemon.
- **REST API**: Full wallet lifecycle management (create, recover, lock, unlock), CoinJoin control (maker/taker), and transaction operations.
- **WebSocket**: Real-time notifications for CoinJoin state and transactions.
- **Secure Auth**: JWT-based authentication with access/refresh tokens.
- **Orderbook Proxy**: Built-in proxy for the orderbook watcher service.

## Installation

`jmwalletd` is part of the joinmarket-ng monorepo.

```bash
pip install jmwalletd
```

## Usage

Start the daemon:

```bash
jmwalletd
```

By default, it listens on `https://localhost:28183` and `wss://localhost:28283`.

### Configuration

The daemon uses the standard JoinMarket configuration file (`joinmarket.cfg` or equivalent TOML). Key settings:

- `[DAEMON] no_daemon_tor`: Set to `true` to disable Tor for the daemon (useful for local dev/Docker).
- `[BLOCKCHAIN] network`: `mainnet`, `testnet`, `signet`, or `regtest`.

## Development

Run tests:

```bash
pytest jmwalletd/
```
