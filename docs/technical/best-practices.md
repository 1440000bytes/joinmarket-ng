# Best Practices

This page collects the practical guidance users and makers should follow on
top of the default configuration. Each section links to the canonical
technical pages for more depth.

## Backups

- **Back up every key that controls funds.** The JoinMarket mnemonic recovers
  wallet-derived outputs and bonds. An external-key bond additionally requires
  the external signer seed or key, any BIP39 passphrase, and its derivation path.
- **Record fidelity bond metadata.** For each active bond, store the
  derivation path and locktime in your backup. A wallet-derived bond can be
  spent from the JoinMarket mnemonic alone, but the metadata makes recovery
  faster. An external-key bond also requires its external seed or key, any
  passphrase, and the exact key origin. See
  [Fidelity Bond Operations](../fidelity-bond-operations.md) and [Wallet](wallet.md)
  for recovery details.
- **Back up before any major change.** Re-confirm the mnemonic and bond
  metadata before upgrades, re-imports, or hardware migrations.

## Mixdepth Hygiene

- **Treat mixdepths as privacy boundaries.** Do not mix funds across
  mixdepths. Built-in flows
  (taker, tumbler, maker change) respect this boundary; manual spends from
  the wallet CLI do not.
- **Prefer `INTERNAL` destinations across mixdepths** when building privacy
  in steps. External destinations (deposits to exchanges, payments) should
  be sourced from the highest-mixdepth coins you have, not coins you just
  received.
- **Run multiple smaller rounds over time** instead of one large round. This
  is harder to subset-sum analyze, and avoids large change outputs
  that stand out on chain.

## Fidelity Bonds

- **Anonymize bond UTXOs before locking them.** A bond reveals its UTXO
  publicly on directories, so any history attached to that UTXO becomes
  attached to your maker identity. Coin-control the funds, run them through
  a few CoinJoin rounds, and only then lock them into a bond. See
  [Privacy](privacy.md) for the full rationale.
- **Use a dedicated mnemonic for fidelity bonds.**
  The bond mnemonic only holds bond funds, which are locked and not
  required for the maker operation, since they can sign a delegated certificate.
  It is safer but requires a separate backup; see
  [Fidelity Bond Operations](../fidelity-bond-operations.md#backups-and-compromise).
- **Prefer hardware-wallet-signed bonds when possible.** Blockstream Jade
  and Specter DIY can sign bond redemptions. Original Digital BitBox / BitBox01
  support is expected from its raw-digest signing design but is untested and
  the device is EOL. Ledger works only with the legacy Bitcoin app (2.0.x and
  earlier -- the current app has been reported to reject bond PSBTs). Trezor,
  Coldcard, BitBox02, and KeepKey currently cannot. Always test the full
  create-and-spend flow before funding a bond;
  you can check any device model risk-free with the public test mnemonic
  described in [Fidelity Bond Operations](../fidelity-bond-operations.md#testing-device-compatibility-with-the-public-test-mnemonic).

## Taker Operation

- **Use multiple directories.** Configure several directory nodes so the
  loss or compromise of one does not silently degrade your offer view. See
  [Configuration](configuration.md).
- **Verify maker offers stay within your fee budget** before sending. The
  taker enforces caps you configure; pick conservative defaults.

## Maker Operation

- **Use the Bitcoin Core `descriptor_wallet` backend.** It is the most
  compatible and best-tested backend (see [Wallet](wallet.md)).
- **Run with Tor control enabled** so the maker can create ephemeral onion
  services and accept direct connections.
- **Monitor balance and logs.** Use the watchdog / monitoring of your
  choice to catch silent loss of funds or repeated failed signs early.

## Operators and Contributors

- Keep docs focused on defaults and working paths; avoid duplicate deep
  dives.
- Prefer linking to one canonical page per topic.
- Validate docs by running commands in a clean environment.
