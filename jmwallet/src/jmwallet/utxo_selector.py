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
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from jmwallet.utxo_tui import (
    adjust_scroll,
    build_display_items,
    seek_selectable,
)
from jmwallet.wallet.utxo_metadata import AUTO_FREEZE_REUSE_LABEL

if TYPE_CHECKING:
    from jmwallet.wallet.models import UTXOInfo


_CONTROLS_HINT = (
    " Space/Tab = toggle | j/k = navigate | s = select all in md | "
    "d = deselect all in md | Enter = confirm | q = cancel"
)


def format_utxo_line(
    utxo: UTXOInfo,
    max_width: int = 120,
    prev_address: str = "",
    excluded_outpoints: set[tuple[str, int]] | None = None,
    term_width: int = 120,
) -> str:
    """Format a single UTXO row with separate Label and State columns."""
    md_str = f"m{utxo.mixdepth}"

    # Calculate address column width
    addr_col_width = max(12, term_width - 95)

    # All addresses use the calculated column width.
    if utxo.address == prev_address:
        addr_str = "..."
    else:
        if len(utxo.address) > addr_col_width:
            # Middle-ellipsis: show start...end
            prefix_len = (addr_col_width - 3) // 2
            suffix_len = addr_col_width - 3 - prefix_len
            addr_str = utxo.address[:prefix_len] + "..." + utxo.address[-suffix_len:]
        else:
            addr_str = utxo.address

    amount_str = f"{utxo.value:,} sats"
    conf_str = f"{utxo.confirmations:>8,}"

    # Outpoint: first 8 txid chars and vout, padded for column alignment
    outpoint = f"{utxo.txid[:8]}...:{utxo.vout}"

    # Label column: FB status for fidelity bonds; remap "non-cj-change" to the
    # shorter "reg-change" so it fits the 11-char column.
    if utxo.is_fidelity_bond:
        label_col = "FB-active" if utxo.is_locked else "FB-expired"
    else:
        label_col = "reg-change" if utxo.label == "non-cj-change" else (utxo.label or "")

    state_col = _utxo_state_col(utxo, excluded_outpoints)

    # Build the line with dynamic address column width
    line = (
        f"{md_str:>2} | {addr_str:<{addr_col_width}} | {amount_str:>15} | {conf_str:>8} | "
        f"{outpoint:<15} | {label_col:<11} | {state_col:<9} |"
    )

    if len(line) > max_width:
        line = line[: max_width - 3] + "..."

    return line


def _utxo_state_col(utxo: UTXOInfo, excluded_outpoints: set[tuple[str, int]] | None = None) -> str:
    """Return the State-column value for a UTXO (also used in the footer).

    Priority order: in-use (CoinJoin active) overrides everything, then frozen
    (user locked), then locked (FB timelock active); default is spendable.
    """
    if excluded_outpoints and (utxo.txid, utxo.vout) in excluded_outpoints:
        return "in-use"
    if utxo.frozen:
        return "frozen"
    if utxo.is_fidelity_bond and utxo.is_locked:
        return "locked"
    return "spendable"


def _is_address_reused(
    utxo: UTXOInfo,
    address_utxo_counts: dict[str, int],
) -> bool:
    """Whether a UTXO shares its address with other UTXOs (reduces privacy).

    Reuse is detected the same way for the table's RU! indicator and the
    footer's RU explanation.
    """
    return address_utxo_counts.get(utxo.address, 0) > 1 or utxo.label == AUTO_FREEZE_REUSE_LABEL


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


def _draw_header(stdscr: curses.window, width: int) -> str:
    """Draw the title bar and the table header, returning the header line.

    The returned header line is used to size the row separators and the
    footer separators.
    """
    header = " — UTXO Selector —"
    stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
    stdscr.addstr(1, 0, header.center(width)[:width])
    stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)

    # Calculate address column width
    addr_col_width = max(12, width - 95)

    # Build dynamic header with calculated address width
    header_line = (
        f"  | Sel | MD | {'Address':^{addr_col_width}} |      Amount     | "
        f"{'Confs':^8} |    Outpoint     |    Label    |   State   |"
    )
    stdscr.addstr(3, 0, header_line[: width - 1])
    header_sep_width = min(len(header_line) - 2, width - 3)
    stdscr.addstr(4, 2, "|", curses.A_NORMAL)
    stdscr.addstr(4, 3, "-" * (header_sep_width - 2), curses.color_pair(3))
    right_pos = 3 + header_sep_width - 2
    if right_pos < width - 1:
        stdscr.addstr(4, right_pos, "|", curses.A_NORMAL)
    return header_line


def _draw_utxo_rows(
    stdscr: curses.window,
    display_items: list[UTXOInfo | None],
    selected: set[int],
    cursor_pos: int,
    scroll_offset: int,
    list_height: int,
    list_start: int,
    width: int,
    sep_width: int,
    excluded_outpoints: set[tuple[str, int]],
    address_utxo_counts: dict[str, int],
    is_selectable: Callable[[int], bool],
) -> None:
    """Draw the visible UTXO rows with separators, marks and colors."""
    prev_address = ""
    for i, item in enumerate(display_items):
        if i < scroll_offset or i >= scroll_offset + list_height:
            continue

        display_row = list_start + (i - scroll_offset)

        if item is None:
            try:
                # Draw separator with white outer borders
                stdscr.addstr(display_row, 0, "  ", curses.A_NORMAL)
                stdscr.addstr(display_row, 2, "|", curses.A_NORMAL)
                stdscr.addstr(
                    display_row,
                    3,
                    "-" * (sep_width - 2),
                    curses.color_pair(3) | curses.A_DIM,
                )
                right_sep_pos = 3 + sep_width - 2
                if right_sep_pos < width - 1:
                    stdscr.addstr(display_row, right_sep_pos, "|", curses.A_NORMAL)
            except curses.error:
                pass
            prev_address = ""
            continue

        is_selected = i in selected
        is_cursor = i == cursor_pos

        if not is_selectable(i):
            mark = "[-]"
        elif is_selected:
            mark = "[x]"
        else:
            mark = "[ ]"
        line = f"| {mark} | " + format_utxo_line(
            item, width - 8, prev_address, excluded_outpoints, width
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
            # Left indent, then left border in default color (white)
            stdscr.addstr(display_row, 0, "  ", curses.A_NORMAL)
            stdscr.addstr(display_row, 2, "|", curses.A_NORMAL)

            # Row content without outer borders, preserving spacing for alignment
            content_to_write = ""
            right_border_pos = 0
            if len(line) >= 2:
                inner_content = line[1:-1] if line.endswith("|") else line[1:]
                content_to_write = inner_content[: width - 4]
                stdscr.addstr(display_row, 3, content_to_write, attr)

                # Right border aligned with content end
                right_border_pos = 3 + len(content_to_write)
                if right_border_pos < width - 1:
                    stdscr.addstr(display_row, right_border_pos, "|", curses.A_NORMAL)

            # RU! indicator for address reuse
            is_reused = _is_address_reused(item, address_utxo_counts)
            if is_reused:
                ru_pos = right_border_pos + 1 if right_border_pos > 0 else 4
                if ru_pos < width - 4:
                    try:
                        stdscr.addstr(
                            display_row, ru_pos, " RU!", curses.color_pair(4) | curses.A_BOLD
                        )
                    except curses.error:
                        pass
        except curses.error:
            pass  # Ignore if we write past the edge


def _build_footer_lines(
    display_items: list[UTXOInfo | None],
    selected: set[int],
    base_selectable: set[int],
    is_selectable: Callable[[int], bool],
    target_amount: int,
    allowed_mixdepth: int | None,
    pinned: int | None,
    cursor_pos: int,
    excluded_outpoints: set[tuple[str, int]],
    address_utxo_counts: dict[str, int],
) -> tuple[str, str, str, str]:
    """Build the footer text lines, returning (line1, line2, line4, ru_note).

    ``line1`` is the selection summary, ``line2`` the (optional) pinned source
    mixdepth, ``line4`` the cursor status with the State column appended and
    ``ru_note`` an optional address-reuse warning.
    """
    selected_utxos = [display_items[i] for i in selected]
    total_selected = sum(u.value for u in selected_utxos if u is not None)
    total_str = f"{total_selected:,} sats"
    selectable_count = sum(1 for i in base_selectable if is_selectable(i))

    if target_amount > 0:
        remaining = target_amount - total_selected
        target_str = f"{target_amount:,} sats"
        if remaining > 0:
            footer_line1 = f" Target: {target_str} | Need: {remaining:,} sats more |"
        else:
            footer_line1 = f" Target: {target_str} | Excess: {-remaining:,} sats |"
    else:
        footer_line1 = " Sweep mode |"

    footer_line1 += f" Selected: {len(selected)}/{selectable_count} UTXOs | Total: {total_str}"

    footer_line2 = ""
    if pinned is not None:
        if allowed_mixdepth is not None:
            footer_line2 = f" Source mixdepth: m{pinned}"
        else:
            footer_line2 = f" Source mixdepth: m{pinned} (deselect all UTXOs to change)"

    # Context-sensitive status line for the item under cursor
    cursor_item = display_items[cursor_pos] if cursor_pos < len(display_items) else None
    footer_line4 = ""
    ru_note = ""
    if cursor_item is not None:
        if cursor_item.is_fidelity_bond:
            if cursor_item.is_locked:
                footer_line4 = (
                    f"Active Fidelity Bond: Locked and not spendable until "
                    f"{datetime.fromtimestamp(cursor_item.locktime).strftime('%Y-%m-%d')}!"
                )
            else:
                footer_line4 = "Expired Fidelity Bond, free to spend"
        elif cursor_item.label == "cj-change":
            footer_line4 = "Change output from a CoinJoin (deanonymising, keep separate)"
        elif cursor_item.label == "cj-out":
            footer_line4 = "CoinJoin output (mixed funds)"
        elif cursor_item.label in ("reg-change", "non-cj-change"):
            footer_line4 = "Regular change (not from CoinJoin)"
        elif cursor_item.label == "deposit":
            footer_line4 = "Address with funds from internal or external sources"
        elif cursor_item.label:
            footer_line4 = f"Label: {cursor_item.label}"

        # Append the current State (same logic as the table's State column).
        state_col = _utxo_state_col(cursor_item, excluded_outpoints)
        if footer_line4:
            footer_line4 = f"{footer_line4}  •  State: {state_col}"
        else:
            footer_line4 = f"State: {state_col}"
        # RU note for address reuse (same logic as the table's RU! indicator).
        is_reused = _is_address_reused(cursor_item, address_utxo_counts)
        if is_reused:
            ru_note = "  •  Warning: Address reuse - (reduces privacy!)"

    return footer_line1, footer_line2, footer_line4, ru_note


def _draw_footer(
    stdscr: curses.window,
    height: int,
    width: int,
    header_line: str,
    footer_line1: str,
    footer_line2: str,
    footer_line4: str,
    ru_note: str,
) -> None:
    """Draw the footer: selection summary, cursor status and controls."""
    # Footer structure: Selection Details | UTXO Status | Controls
    footer_y = height - 12

    # Footer drawing wrapped in try/except to handle resize gracefully
    try:
        # Separators aligned with table content (2 spaces indent)
        sep_width = min(len(header_line) - 2, width - 3)
        stdscr.addstr(footer_y, 2, "-" * sep_width)

        stdscr.attron(curses.A_BOLD)
        # Selection Details section
        stdscr.addstr(footer_y + 1, 2, "Selection Details")
        stdscr.addstr(footer_y + 2, 2, footer_line1[: width - 3])

        # Source mixdepth
        if footer_line2:
            stdscr.addstr(footer_y + 3, 2, footer_line2[: width - 3])
            next_y = footer_y + 4
        else:
            next_y = footer_y + 3

        # UTXO Status section
        stdscr.addstr(next_y, 2, "-" * sep_width)
        stdscr.addstr(next_y + 1, 2, "UTXO Status")
        if footer_line4:
            stdscr.attron(curses.A_DIM)
            stdscr.addstr(next_y + 2, 3, footer_line4[: width - 3])
            stdscr.attroff(curses.A_DIM)
            if ru_note:
                # RU explanation in red, like the table's RU! indicator
                ru_col = 3 + len(footer_line4)
                if ru_col < width - 1:
                    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                    stdscr.addstr(
                        next_y + 2,
                        ru_col,
                        ru_note[: width - 3 - len(footer_line4)],
                    )
                    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
            next_y += 3  # separator + header + status line
        else:
            next_y += 2  # separator + header only

        # Controls section, pinned so the key line always ends 3 rows from the
        # bottom (exactly 2 empty rows below it), regardless of active status lines
        stdscr.addstr(height - 5, 2, "-" * sep_width)
        stdscr.addstr(height - 4, 2, "Controls")
        stdscr.addstr(height - 3, 2, _CONTROLS_HINT[: width - 3])

        stdscr.attroff(curses.A_BOLD)
    except curses.error:
        pass


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
        excluded_outpoints: In-flight CoinJoin inputs shown as State ``in-use``
            with a ``[-]`` mark; unavailable for selection

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
    curses.init_pair(4, curses.COLOR_RED, -1)  # Locked FBs / frozen or in-use UTXOs / RU! warnings
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # Unlocked fidelity bonds (can be spent)

    selected: set[int] = set()
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

    # Address reuse detection: count UTXOs per address
    address_utxo_counts: dict[str, int] = {}
    for item in display_items:
        if item is not None:
            address_utxo_counts[item.address] = address_utxo_counts.get(item.address, 0) + 1

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Prevent crash on very small terminals
        if height < 15 or width < 40:
            msg = "Terminal too small. Please resize."
            try:
                stdscr.addstr(0, 0, msg)
                stdscr.refresh()
            except curses.error:
                pass
            stdscr.getch()
            continue

        header_line = _draw_header(stdscr, width)

        # Calculate visible area
        list_start = 5
        list_height = (
            height - 17
        )  # Reserve space for header, footer and 2 empty lines at the bottom

        scroll_offset = adjust_scroll(cursor_pos, scroll_offset, list_height)

        # Display UTXOs (with mixdepth separators)
        sep_width = min(len(header_line) - 2, width - 3)

        _draw_utxo_rows(
            stdscr,
            display_items,
            selected,
            cursor_pos,
            scroll_offset,
            list_height,
            list_start,
            width,
            sep_width,
            excluded_outpoints,
            address_utxo_counts,
            is_selectable,
        )

        # Footer with selection summary
        pinned = pinned_mixdepth()
        footer_line1, footer_line2, footer_line4, ru_note = _build_footer_lines(
            display_items,
            selected,
            base_selectable,
            is_selectable,
            target_amount,
            allowed_mixdepth,
            pinned,
            cursor_pos,
            excluded_outpoints,
            address_utxo_counts,
        )
        _draw_footer(
            stdscr,
            height,
            width,
            header_line,
            footer_line1,
            footer_line2,
            footer_line4,
            ru_note,
        )

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

        elif key == ord("s"):  # Select all selectable UTXOs in one mixdepth
            # Use the pinned mixdepth when set, else the mixdepth under the
            # cursor; a spend can never mix coins from different mixdepths.
            target_md = pinned
            if target_md is None:
                cursor_item = display_items[cursor_pos]
                if cursor_item is not None:
                    target_md = cursor_item.mixdepth
            if target_md is not None:
                for i in base_selectable:
                    item = display_items[i]
                    if item is not None and item.mixdepth == target_md:
                        selected.add(i)

        elif key == ord("d"):  # Deselect all
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
    - PgUp/PgDn: Page up/down
    - Tab/Space: Toggle selection
    - Enter: Confirm selection
    - q/Escape: Cancel
    - s: Select all (in the pinned/cursor mixdepth)
    - d: Deselect all
    - g/G: Go to top/bottom

    Args:
        utxos: List of available UTXOs to choose from (any mixdepth)
        target_amount: Target amount in sats (0 for sweep, used for display)
        allowed_mixdepth: When set, restrict selection to this mixdepth
            (other mixdepths are displayed for context only)
        min_confirmations: UTXOs below this many confirmations are shown
            but unselectable
        excluded_outpoints: In-flight CoinJoin inputs shown as State ``in-use``
            with a ``[-]`` mark; unavailable for selection.

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

    # Sort UTXOs by derivation path (same order as freeze manager) and add separators
    sorted_utxos = sorted(utxos, key=lambda u: u.path)
    display_items = build_display_items(sorted_utxos)

    return curses.wrapper(
        _run_selector,
        display_items,
        target_amount,
        allowed_mixdepth,
        min_confirmations,
        excluded_outpoints,
    )
