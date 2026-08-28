"""
User confirmation prompts for fund-moving operations.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any


def is_interactive_mode() -> bool:
    """
    Check if we're running in interactive mode.

    Returns False if NO_INTERACTIVE env var is set or if not attached to a TTY.
    """
    if os.environ.get("NO_INTERACTIVE"):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


# Display width for coinjoin confirmation
_COINJOIN_WIDTH = 96
_LABEL_WIDTH = 16  # Width for labels like "CoinJoin Amount:"
_SEND_WIDTH = 80  # Display width for standard send confirmation


def _format_fee_percentage(fee: int, amount: int) -> str:
    """Format a fee percentage when a positive CoinJoin amount is available."""
    if amount <= 0:
        return ""
    return f" ({fee / amount * 100:.4f}%)"


def _display_coinjoin_send_confirmation(
    amount: int,
    destination: str | None,
    mining_fee: int | None,
    additional_info: dict[str, Any] | None,
    stage: str = "",
) -> None:
    """Display coinjoin confirmation in column format."""
    from jmcore.bitcoin import format_amount

    print("\n" + "=" * _COINJOIN_WIDTH)
    if stage == "broadcast":
        print("FINAL COINJOIN Transaction -- ready to broadcast")
    elif stage == "initial":
        print("Expected COINJOIN Transaction -- fee estimates, confirm makers")
    else:
        print("Expected COINJOIN Transaction")
    print("=" * _COINJOIN_WIDTH)

    # Extract info from additional_info
    source_mixdepth = additional_info.get("Source Mixdepth") if additional_info else None
    makers = additional_info.get("Makers", []) if additional_info else []
    total_maker_fee = additional_info.get("Total Maker Fee", 0) if additional_info else 0
    fee_rate = additional_info.get("Fee Rate") if additional_info else None

    # Source Mixdepth
    if source_mixdepth is not None:
        print(f"{'Source Mixdepth:':<{_LABEL_WIDTH}}  {source_mixdepth}")

    # Destination
    if destination:
        if destination == "INTERNAL":
            print(f"{'Destination:':<{_LABEL_WIDTH}}  INTERNAL (next mixdepth)")
        else:
            print(f"{'Destination:':<{_LABEL_WIDTH}}  {destination}")

    # CoinJoin Amount
    if amount == 0:
        print(f"{'CoinJoin Amount:':<{_LABEL_WIDTH}}  SWEEP (all available funds)")
    else:
        print(f"{'CoinJoin Amount:':<{_LABEL_WIDTH}}  {format_amount(amount)}")

    # Makers (formatted with alignment)
    if makers:
        # First maker line includes label
        label = f"Makers ({len(makers)}):"
        for i, maker_str in enumerate(makers):
            if i == 0:
                print(f"{label:<{_LABEL_WIDTH}}  {i + 1}. {maker_str}")
            else:
                print(f"{'':<{_LABEL_WIDTH}}  {i + 1}. {maker_str}")

    # Total Maker Fee
    if makers:
        print(
            f"{'Total Maker Fee:':<{_LABEL_WIDTH}}  {total_maker_fee:,} sats"
            f"{_format_fee_percentage(total_maker_fee, amount)}"
        )

    # Miner Fee Rate
    if fee_rate is not None:
        print(f"{'Miner Fee Rate:':<{_LABEL_WIDTH}}  {fee_rate:.2f} sat/vB")

    # Mining fee
    if mining_fee is not None:
        print(
            f"{'Miner Fee:':<{_LABEL_WIDTH}}  {format_amount(mining_fee)}"
            f"{_format_fee_percentage(mining_fee, amount)}"
        )

    # Total Fee (maker fee + miner fee)
    if mining_fee is not None and makers:
        total_fee = mining_fee + total_maker_fee
        print(
            f"{'Total Fee:':<{_LABEL_WIDTH}}  {format_amount(total_fee)}"
            f"{_format_fee_percentage(total_fee, amount)}"
        )

    print("=" * _COINJOIN_WIDTH)


def _display_standard_send_confirmation(
    operation: str,
    amount: int,
    destination: str | None,
    fee: int | None,
    mining_fee: int | None,
    additional_info: dict[str, Any] | None,
) -> None:
    """Display standard transaction confirmation (non-coinjoin).

    Layout follows the workflow ordering proposed in issue #107:
    source mixdepth, destination, amount, change, fee rate, miner fee. Field
    labels are aligned in a left-aligned column for readability.
    """
    from jmcore.bitcoin import format_amount

    print("\n" + "=" * _SEND_WIDTH)
    print(f"Expected {operation.upper()} Transaction")
    print("=" * _SEND_WIDTH)

    # Consume known keys from additional_info; any remaining keys are
    # rendered after the known fields to preserve forward compatibility
    # with callers that pass custom metadata. We accept both the legacy
    # "Fee Rate" and the new "Miner Fee Rate" key for the rate field.
    info = dict(additional_info) if additional_info else {}
    source_mixdepth = info.pop("Source Mixdepth", None)
    change = info.pop("Change", None)
    fee_rate = info.pop("Miner Fee Rate", None)
    if fee_rate is None:
        fee_rate = info.pop("Fee Rate", None)
    else:
        # Drop the legacy alias if both keys were passed, to avoid double rendering.
        info.pop("Fee Rate", None)

    # Source Mixdepth
    if source_mixdepth is not None:
        print(f"{'Source Mixdepth:':<{_LABEL_WIDTH}}  {source_mixdepth}")

    # Destination
    if destination:
        if destination == "INTERNAL":
            print(f"{'Destination:':<{_LABEL_WIDTH}}  INTERNAL (next mixdepth)")
        else:
            print(f"{'Destination:':<{_LABEL_WIDTH}}  {destination}")

    # Amount
    if amount == 0:
        print(f"{'Amount:':<{_LABEL_WIDTH}}  SWEEP (all available funds)")
    else:
        print(f"{'Amount:':<{_LABEL_WIDTH}}  {format_amount(amount)}")

    # Change
    if change is not None:
        print(f"{'Change:':<{_LABEL_WIDTH}}  {change}")

    # Miner Fee Rate (renamed from "Fee Rate" for clarity since SEND has no
    # maker fees, only network/miner fees)
    if fee_rate is not None:
        print(f"{'Miner Fee Rate:':<{_LABEL_WIDTH}}  {fee_rate}")

    # Miner Fee: prefer mining_fee, fall back to the legacy fee argument.
    effective_mining_fee = mining_fee if mining_fee is not None else fee
    if effective_mining_fee is not None:
        print(f"{'Miner Fee:':<{_LABEL_WIDTH}}  {format_amount(effective_mining_fee)}")

    # Render any remaining custom keys for forward compatibility.
    for key, value in info.items():
        if isinstance(value, int) and key.lower().endswith(("fee", "amount", "value")):
            print(f"{key + ':':<{_LABEL_WIDTH}}  {format_amount(value)}")
        elif isinstance(value, list):
            print(f"{key + ':':<{_LABEL_WIDTH}}  {len(value)} item(s)")
            for i, item in enumerate(value, 1):
                print(f"  {i}. {item}")
        else:
            print(f"{key + ':':<{_LABEL_WIDTH}}  {value}")

    print("=" * _SEND_WIDTH)


def _prepare_confirmation(
    operation: str,
    amount: int,
    destination: str | None = None,
    fee: int | None = None,
    mining_fee: int | None = None,
    additional_info: dict[str, Any] | None = None,
    skip_confirmation: bool = False,
    stage: str = "",
) -> bool:
    """Validate interactivity, display transaction details, and prepare stdin."""
    if skip_confirmation:
        return False

    if not is_interactive_mode():
        raise RuntimeError(
            "Cannot prompt for confirmation in non-interactive mode. "
            "Use --yes flag or set NO_INTERACTIVE=1 to skip confirmation."
        )

    # Use different display for coinjoin vs regular transactions
    if operation.lower() == "coinjoin":
        _display_coinjoin_send_confirmation(
            amount=amount,
            destination=destination,
            mining_fee=mining_fee,
            additional_info=additional_info,
            stage=stage,
        )
    else:
        _display_standard_send_confirmation(
            operation=operation,
            amount=amount,
            destination=destination,
            fee=fee,
            mining_fee=mining_fee,
            additional_info=additional_info,
        )

    sys.stdout.flush()
    try:
        import termios

        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except ImportError:
        pass
    except (OSError, ValueError):
        pass
    return True


def _read_confirmation_response() -> bool:
    """Read a synchronous y/N response from stdin."""
    try:
        response = input("\nProceed with this transaction? [y/N]: ").strip().lower()
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\n\nTransaction cancelled by user.")
        return False


def confirm_transaction(
    operation: str,
    amount: int,
    destination: str | None = None,
    fee: int | None = None,
    mining_fee: int | None = None,
    additional_info: dict[str, Any] | None = None,
    skip_confirmation: bool = False,
    stage: str = "",
) -> bool:
    """Prompt synchronously for confirmation of a fund-moving transaction."""
    should_prompt = _prepare_confirmation(
        operation=operation,
        amount=amount,
        destination=destination,
        fee=fee,
        mining_fee=mining_fee,
        additional_info=additional_info,
        skip_confirmation=skip_confirmation,
        stage=stage,
    )
    return _read_confirmation_response() if should_prompt else True


async def confirm_transaction_async(
    operation: str,
    amount: int,
    destination: str | None = None,
    fee: int | None = None,
    mining_fee: int | None = None,
    additional_info: dict[str, Any] | None = None,
    skip_confirmation: bool = False,
    stage: str = "",
) -> bool:
    """Prompt without blocking the event loop when stdin readers are supported.

    Cancellation removes the registered reader, so a timed-out initial CoinJoin
    prompt cannot consume input intended for a later operation. Event loops that
    cannot watch stdin fall back to the synchronous prompt; callers must still
    enforce freshness after it returns.
    """
    should_prompt = _prepare_confirmation(
        operation=operation,
        amount=amount,
        destination=destination,
        fee=fee,
        mining_fee=mining_fee,
        additional_info=additional_info,
        skip_confirmation=skip_confirmation,
        stage=stage,
    )
    if not should_prompt:
        return True

    loop = asyncio.get_running_loop()
    response_future: asyncio.Future[str] = loop.create_future()
    reader_registered = False

    def read_ready() -> None:
        if response_future.done():
            return
        try:
            response_future.set_result(sys.stdin.readline())
        except Exception as exc:
            response_future.set_exception(exc)

    try:
        try:
            loop.add_reader(sys.stdin.fileno(), read_ready)
            reader_registered = True
        except (AttributeError, NotImplementedError):
            return _read_confirmation_response()

        print("\nProceed with this transaction? [y/N]: ", end="", flush=True)
        try:
            response = await response_future
        except asyncio.CancelledError:
            print()
            raise
        if response == "":
            print("\n\nTransaction cancelled by user.")
            return False
        return response.strip().lower() in ("y", "yes")
    finally:
        if reader_registered:
            loop.remove_reader(sys.stdin.fileno())


def format_maker_summary(
    makers: list[dict[str, Any]], fee_rate: float | None = None, amount: int | None = None
) -> dict[str, Any]:
    """
    Format maker information for confirmation display.

    Args:
        makers: List of selected maker dicts with 'nick', 'fee', 'bond_value', 'location', etc.
        fee_rate: Fee rate in sat/vB (optional)
        amount: CoinJoin amount in satoshis, used to display fee percentages (optional)

    Returns:
        Dict with formatted maker info for confirmation display
    """
    total_maker_fee = sum(m.get("fee", 0) for m in makers)

    # Find max widths for alignment
    max_fee_width = max((len(f"{m.get('fee', 0):,}") for m in makers), default=1)
    max_bond_width = max((len(f"{m.get('bond_value', 0):,}") for m in makers), default=1)

    maker_details = []
    for m in makers:
        nick = m.get("nick", "unknown")
        fee = m.get("fee", 0)
        bond_value = m.get("bond_value", 0)
        location = m.get("location")

        # Right-align fee and bond values
        fee_str = f"{fee:>{max_fee_width},}"
        fee_percentage = _format_fee_percentage(fee, amount) if amount is not None else ""
        bond_str = f" [bond: {bond_value:>{max_bond_width},}]" if bond_value > 0 else " [no bond]"

        # Add location info if available
        if location and location != "NOT-SERVING-ONION":
            # Truncate onion address for readability (show first 16 chars)
            if ":" in location:
                onion, port = location.rsplit(":", 1)
                if onion.endswith(".onion") and len(onion) > 20:
                    location_str = f" @ {onion[:16]}...:{port}"
                else:
                    location_str = f" @ {location}"
            else:
                location_str = f" @ {location[:20]}..."
            maker_details.append(f"{nick}: {fee_str} sats{fee_percentage}{bond_str}{location_str}")
        else:
            maker_details.append(f"{nick}: {fee_str} sats{fee_percentage}{bond_str}")

    result: dict[str, Any] = {
        "Total Maker Fee": total_maker_fee,
        "Makers": maker_details,
    }

    if fee_rate is not None:
        result["Fee Rate"] = fee_rate

    return result
