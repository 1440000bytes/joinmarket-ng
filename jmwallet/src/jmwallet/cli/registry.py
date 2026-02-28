"""
Bond registry command: registry-show.

registry-list and registry-sync have been merged into list-bonds
(see bonds.py).  list-bonds works in two modes:
  - Without --mnemonic-file: shows bonds from the local registry (offline).
  - With --mnemonic-file: scans the blockchain and updates the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from jmcore.cli_common import setup_logging

from jmwallet.cli import app


@app.command("registry-show")
def registry_show(
    address: Annotated[str, typer.Argument(help="Bond address to show")],
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Data directory (default: ~/.joinmarket-ng or $JOINMARKET_DATA_DIR)",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON"),
    ] = False,
    log_level: Annotated[str, typer.Option("--log-level", "-l")] = "WARNING",
) -> None:
    """Show detailed information about a specific fidelity bond."""
    setup_logging(log_level)

    from jmcore.btc_script import disassemble_script
    from jmcore.paths import get_default_data_dir

    from jmwallet.wallet.bond_registry import load_registry

    resolved_data_dir = data_dir if data_dir else get_default_data_dir()
    registry = load_registry(resolved_data_dir)

    bond = registry.get_bond_by_address(address)
    if not bond:
        print(f"\nBond not found: {address}")
        print(f"Registry: {resolved_data_dir / 'fidelity_bonds.json'}")
        raise typer.Exit(1)

    if json_output:
        import json

        print(json.dumps(bond.model_dump(), indent=2))
        return

    print("\n" + "=" * 80)
    print("FIDELITY BOND DETAILS")
    print("=" * 80)
    print(f"\nAddress:          {bond.address}")
    print(f"Network:          {bond.network}")
    print(f"Index:            {bond.index}")
    print(f"Path:             {bond.path}")
    print(f"Public Key:       {bond.pubkey}")
    print()
    print(f"Locktime:         {bond.locktime} ({bond.locktime_human})")
    if bond.is_expired:
        print("Status:           EXPIRED (can be spent)")
    else:
        remaining = bond.time_until_unlock
        days = remaining // 86400
        hours = (remaining % 86400) // 3600
        print(f"Status:           LOCKED ({days}d {hours}h remaining)")
    print()
    print("-" * 80)
    print("WITNESS SCRIPT")
    print("-" * 80)
    witness_script = bytes.fromhex(bond.witness_script_hex)
    print(f"Hex:          {bond.witness_script_hex}")
    print(f"Disassembled: {disassemble_script(witness_script)}")
    print()
    print("-" * 80)
    print("FUNDING STATUS")
    print("-" * 80)
    if bond.is_funded:
        print(f"TXID:         {bond.txid}")
        print(f"Vout:         {bond.vout}")
        print(f"Value:        {bond.value:,} sats")
        print(f"Confirmations: {bond.confirmations}")
    else:
        print("Not funded (or not yet synced)")
    print()
    print(f"Created:      {bond.created_at}")
    print("=" * 80 + "\n")
