"""
Interactive UTXO selector TUI.

Shows every UTXO in the wallet grouped by mixdepth (same layout as the
freeze manager) so the user can compare coins across the whole wallet
before picking which one(s) to spend.

A spend can only draw from a single mixdepth, so the selector pins the
source mixdepth to the first selected UTXO: while anything is selected,
UTXOs in other mixdepths render as unselectable ``[-]`` rows. Deselecting
everything unpins the mixdepth again. Callers that already know the source
mixdepth can pass ``allowed_mixdepth`` to pin it up front (other mixdepths
are then shown for context only).
"""

from __future__ import annotations

import curses
import sys
from typing import TYPE_CHECKING

from jmcore.bitcoin import format_amount

from jmwallet.utxo_tui import (
    ADDRESS_COL_WIDTH,
    adjust_scroll,
    build_display_items,
    format_address_column,
    seek_selectable,
)

if TYPE_CHECKING:
    from jmwallet.wallet.models import UTXOInfo


# Column header; the widths mirror format_utxo_line() so columns align.
_SELECTOR_COL_HEADER = (
    f" Sel | MD | {'Address':<{ADDRESS_COL_WIDTH}} | {'Amount':>15} | {'Confs':>10} | Outpoint"
)


def format_utxo_line(
    utxo: UTXOInfo,
    max_width: int = 120,
    prev_address: str = "",
    excluded_outpoints: set[tuple[str, int]] | None = None,
) -> str:
    """Format a single UTXO row (without the selection-state prefix).

    Args:
        utxo: The UTXO to format
        max_width: Maximum line width (longer lines are truncated with ``...``)
        prev_address: Address of the previous row; consecutive duplicates
            render blanks so the column stays visually grouped

    Returns:
        Formatted string with mixdepth, address, amount, confirmations,
        outpoint, fidelity bond / frozen / in-use indicators, and label.
    """
    md_str = f"m{utxo.mixdepth}"
    addr_str = format_address_column(utxo.address, prev_address)
    amount_str = f"{utxo.value:,} sats"
    conf_str = f"{utxo.confirmations:>5,} conf"
    outpoint = f"{utxo.txid[:8]}...:{utxo.vout}"

    # Fidelity bond indicator (locked vs unlocked)
    fb_indicator = ""
    if utxo.is_fidelity_bond:
        fb_indicator = " [FB-LOCKED]" if utxo.is_locked else " [FB]"

    # Label/note for UTXO type
    label_str = f" ({utxo.label})" if utxo.label else ""

    # Frozen indicator (placed after label for consistency with --extended view)
    frozen_indicator = " [FROZEN]" if utxo.frozen else ""
    in_use_indicator = (
        " [IN-USE]" if excluded_outpoints and (utxo.txid, utxo.vout) in excluded_outpoints else ""
    )

    line = (
        f"{md_str:>2} | {addr_str:<{ADDRESS_COL_WIDTH}} | {amount_str:>15} | {conf_str} | "
        f"{outpoint}{fb_indicator}{label_str}{frozen_indicator}{in_use_indicator}"
    )

    if len(line) > max_width:
        line = line[: max_width - 3] + "..."

    return line


def _is_base_selectable(
    utxo: UTXOInfo,
    allowed_mixdepth: int | None,
    min_confirmations: int,
    excluded_outpoints: set[tuple[str, int]] | None = None,
) -> bool:
    """Whether a UTXO may ever be selected in this session.

    Frozen UTXOs and still-locked fidelity bonds are never selectable, nor
    are UTXOs below ``min_confirmations`` or outside ``allowed_mixdepth``
    (when pinned by the caller), or in ``excluded_outpoints``. They are still
    displayed for context.
    """
    if utxo.frozen:
        return False
    if utxo.is_fidelity_bond and utxo.is_locked:
        return False
    if utxo.confirmations < min_confirmations:
        return False
    if excluded_outpoints and (utxo.txid, utxo.vout) in excluded_outpoints:
        return False
    if allowed_mixdepth is not None and utxo.mixdepth != allowed_mixdepth:
        return False
    return True


def _run_selector(
    stdscr: curses.window,
    display_items: list[UTXOInfo | None],
    target_amount: int,
    allowed_mixdepth: int | None,
    min_confirmations: int,
    excluded_outpoints: set[tuple[str, int]],
) -> list[UTXOInfo]:
    """Run the curses-based UTXO selector.

    Args:
        stdscr: The curses window
        display_items: UTXOs (with ``None`` mixdepth separators) to display
        target_amount: Target amount in sats (0 for sweep, shown for info)
        allowed_mixdepth: When set, only this mixdepth is selectable
        min_confirmations: UTXOs below this many confirmations are unselectable

    Returns:
        List of selected UTXOs
    """
    # Initialize curses
    curses.curs_set(0)  # Hide cursor
    curses.use_default_colors()

    # Initialize color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # Selected items
    curses.init_pair(2, curses.COLOR_YELLOW, -1)  # Current cursor
    curses.init_pair(3, curses.COLOR_CYAN, -1)  # Header
    curses.init_pair(4, curses.COLOR_RED, -1)  # Locked fidelity bonds / frozen UTXOs
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # Unlocked fidelity bonds (can be spent)

    selected: set[int] = set()
    cursor_pos = 0
    scroll_offset = 0

    # Pre-compute which rows can ever be selected in this session.
    base_selectable: set[int] = {
        i
        for i, item in enumerate(display_items)
        if item is not None
        and _is_base_selectable(item, allowed_mixdepth, min_confirmations, excluded_outpoints)
    }
    last = len(display_items) - 1

    def pinned_mixdepth() -> int | None:
        """The mixdepth the selection is currently pinned to (if any)."""
        if selected:
            item = display_items[next(iter(selected))]
            assert item is not None
            return item.mixdepth
        return allowed_mixdepth

    def is_selectable(index: int) -> bool:
        if index not in base_selectable:
            return False
        pinned = pinned_mixdepth()
        item = display_items[index]
        assert item is not None
        return pinned is None or item.mixdepth == pinned

    # Start on a UTXO row, never on a separator.
    cursor_pos = seek_selectable(display_items, 0, 1, lambda _u: True)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Header
        header = " UTXO Selector - Space/Tab: toggle, Enter: confirm, q: cancel "
        stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(0, 0, header.center(width)[:width])
        stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

        # Column headers
        stdscr.addstr(1, 0, _SELECTOR_COL_HEADER[: width - 1])
        stdscr.addstr(2, 0, "-" * min(len(_SELECTOR_COL_HEADER) + 5, width - 1))

        # Calculate visible area
        list_start = 3
        list_height = height - 7  # Reserve space for header and footer

        scroll_offset = adjust_scroll(cursor_pos, scroll_offset, list_height)

        # Display UTXOs (with mixdepth separators)
        separator = "-" * min(len(_SELECTOR_COL_HEADER) + 5, width - 1)
        prev_address = ""
        for i, item in enumerate(display_items):
            if i < scroll_offset or i >= scroll_offset + list_height:
                continue

            display_row = list_start + (i - scroll_offset)
            if display_row >= height - 4:
                break

            if item is None:
                try:
                    stdscr.addstr(display_row, 0, separator, curses.color_pair(3) | curses.A_DIM)
                except curses.error:
                    pass
                prev_address = ""  # Reset on mixdepth change
                continue

            is_selected = i in selected
            is_cursor = i == cursor_pos

            if not is_selectable(i):
                mark = "[-]"
            elif is_selected:
                mark = "[x]"
            else:
                mark = "[ ]"
            line = f" {mark} | " + format_utxo_line(
                item, width - 8, prev_address, excluded_outpoints
            )
            prev_address = item.address

            # Apply colors
            if is_cursor:
                attr = curses.color_pair(2) | curses.A_REVERSE
            elif is_selected:
                attr = curses.color_pair(1) | curses.A_BOLD
            elif (
                item.frozen
                or (item.is_fidelity_bond and item.is_locked)
                or (item.txid, item.vout) in excluded_outpoints
            ):
                # Frozen, in-use, or still-locked bonds are red and unselectable.
                attr = curses.color_pair(4) | curses.A_DIM
            elif item.is_fidelity_bond:
                # Unlocked FB - magenta (can be spent but should be careful)
                attr = curses.color_pair(5)
            elif not is_selectable(i):
                # Immature, or outside the (pinned) source mixdepth
                attr = curses.A_DIM
            else:
                attr = curses.A_NORMAL

            try:
                stdscr.addstr(display_row, 0, line[: width - 1], attr)
            except curses.error:
                pass  # Ignore if we write past the edge

        # Footer with selection summary
        selected_utxos = [display_items[i] for i in selected]
        total_selected = sum(u.value for u in selected_utxos if u is not None)
        total_str = format_amount(total_selected)
        selectable_count = sum(1 for i in base_selectable if is_selectable(i))
        footer_line1 = f" Selected: {len(selected)}/{selectable_count} UTXOs | Total: {total_str}"

        pinned = pinned_mixdepth()
        if pinned is not None:
            if allowed_mixdepth is not None:
                footer_line1 += f" | Source mixdepth: m{pinned}"
            else:
                footer_line1 += f" | Source mixdepth: m{pinned} (deselect all to change)"

        if target_amount > 0:
            remaining = target_amount - total_selected
            target_str = format_amount(target_amount)
            if remaining > 0:
                footer_line2 = f" Target: {target_str} | Need: {format_amount(remaining)} more "
            else:
                excess_str = format_amount(-remaining)
                footer_line2 = f" Target: {target_str} | Excess: {excess_str} (change) "
        else:
            footer_line2 = " Sweep mode: all selected UTXOs will be spent "

        footer_line3 = (
            " Space/Tab: toggle | j/k: navigate | a: select mixdepth | n: none | "
            "Enter: confirm | q: cancel"
        )

        stdscr.addstr(height - 4, 0, "-" * min(len(_SELECTOR_COL_HEADER) + 5, width - 1))

        stdscr.attron(curses.A_BOLD)
        try:
            stdscr.addstr(height - 3, 0, footer_line1[: width - 1])
            stdscr.addstr(height - 2, 0, footer_line2[: width - 1])
            stdscr.addstr(height - 1, 0, footer_line3[: width - 1])
        except curses.error:
            pass
        stdscr.attroff(curses.A_BOLD)

        stdscr.refresh()

        # Handle input
        key = stdscr.getch()

        if key == ord("q") or key == 27:  # q or Escape
            return []

        if key == ord("\n") or key == curses.KEY_ENTER:  # Enter
            if selected:
                result = [display_items[i] for i in sorted(selected)]
                return [u for u in result if u is not None]
            # If nothing selected but there's only one selectable UTXO, select it
            if len(base_selectable) == 1:
                only = display_items[next(iter(base_selectable))]
                assert only is not None
                return [only]
            # Otherwise require explicit selection
            continue

        if key == ord("\t") or key == ord(" "):  # Tab or Space to toggle
            if cursor_pos in selected:
                selected.discard(cursor_pos)
            elif is_selectable(cursor_pos):
                selected.add(cursor_pos)
            # Move cursor down after toggle attempt
            if cursor_pos < last:
                cursor_pos = seek_selectable(display_items, cursor_pos + 1, 1, lambda _u: True)

        elif key == curses.KEY_UP or key == ord("k"):
            cursor_pos = seek_selectable(display_items, max(0, cursor_pos - 1), -1, lambda _u: True)

        elif key == curses.KEY_DOWN or key == ord("j"):
            cursor_pos = seek_selectable(
                display_items, min(last, cursor_pos + 1), 1, lambda _u: True
            )

        elif key == curses.KEY_PPAGE:  # Page Up
            cursor_pos = seek_selectable(
                display_items, max(0, cursor_pos - list_height), -1, lambda _u: True
            )

        elif key == curses.KEY_NPAGE:  # Page Down
            cursor_pos = seek_selectable(
                display_items, min(last, cursor_pos + list_height), 1, lambda _u: True
            )

        elif key == ord("g"):  # Go to top
            cursor_pos = seek_selectable(display_items, 0, 1, lambda _u: True)

        elif key == ord("G"):  # Go to bottom
            cursor_pos = seek_selectable(display_items, last, -1, lambda _u: True)

        elif key == ord("a"):  # Select all selectable UTXOs in one mixdepth
            # Use the pinned mixdepth when set, else the mixdepth under the
            # cursor; a spend can never mix coins from different mixdepths.
            target_md = pinned_mixdepth()
            if target_md is None:
                cursor_item = display_items[cursor_pos]
                if cursor_item is not None:
                    target_md = cursor_item.mixdepth
            if target_md is not None:
                for i in base_selectable:
                    item = display_items[i]
                    if item is not None and item.mixdepth == target_md:
                        selected.add(i)

        elif key == ord("n"):  # Deselect all
            selected = set()


def select_utxos_interactive(
    utxos: list[UTXOInfo],
    target_amount: int = 0,
    allowed_mixdepth: int | None = None,
    min_confirmations: int = 0,
    excluded_outpoints: set[tuple[str, int]] | None = None,
) -> list[UTXOInfo]:
    """Display an interactive UTXO selector over the whole wallet.

    UTXOs are grouped by mixdepth (freeze-manager layout). Selection is
    limited to a single mixdepth: the first toggled UTXO pins the source
    mixdepth until everything is deselected again.

    Keys:
    - Up/Down or j/k: Navigate
    - Tab/Space: Toggle selection
    - Enter: Confirm selection
    - q/Escape: Cancel
    - a: Select all (in the pinned/cursor mixdepth)
    - n: Deselect all
    - g/G: Go to top/bottom

    Args:
        utxos: List of available UTXOs to choose from (any mixdepth)
        target_amount: Target amount in sats (0 for sweep, used for display)
        allowed_mixdepth: When set, restrict selection to this mixdepth
            (other mixdepths are displayed for context only)
        min_confirmations: UTXOs below this many confirmations are shown
            but unselectable
        excluded_outpoints: In-flight CoinJoin inputs shown as ``[IN-USE]``
            but unavailable for selection.

    Returns:
        List of selected UTXOs (all from one mixdepth), empty if cancelled

    Raises:
        RuntimeError: If not running in a terminal
    """
    # Handle trivial cases without requiring a terminal
    if not utxos:
        return []
    excluded_outpoints = excluded_outpoints or set()

    # For multiple UTXOs, we need a terminal
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # If only one UTXO and no terminal, auto-select it (only if selectable)
        if len(utxos) == 1:
            utxo = utxos[0]
            if not _is_base_selectable(
                utxo, allowed_mixdepth, min_confirmations, excluded_outpoints
            ):
                return []
            return utxos
        raise RuntimeError("Interactive UTXO selection requires a terminal")

    # Sort UTXOs by mixdepth, then by value (descending), and add separators
    sorted_utxos = sorted(utxos, key=lambda u: (u.mixdepth, -u.value))
    display_items = build_display_items(sorted_utxos)

    return curses.wrapper(
        _run_selector,
        display_items,
        target_amount,
        allowed_mixdepth,
        min_confirmations,
        excluded_outpoints,
    )
