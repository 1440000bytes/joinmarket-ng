"""Tests for the shared UTXO TUI helpers (jmwallet.utxo_tui).

These helpers back both the freeze manager and the interactive UTXO
selector: mixdepth separators, predicate-based cursor navigation, the
address column formatting, and scroll adjustment.
"""

from __future__ import annotations

from jmwallet.utxo_tui import (
    ADDRESS_COL_WIDTH,
    adjust_scroll,
    build_display_items,
    format_address_column,
    seek_selectable,
)
from jmwallet.wallet.models import UTXOInfo


def _utxo(mixdepth: int, value: int = 100_000, txid_char: str = "a", vout: int = 0) -> UTXOInfo:
    return UTXOInfo(
        txid=txid_char * 64,
        vout=vout,
        value=value,
        address=f"bcrt1qmd{mixdepth}",
        confirmations=10,
        scriptpubkey="0014" + "aa" * 20,
        path=f"m/84'/0'/{mixdepth}'/0/0",
        mixdepth=mixdepth,
    )


class TestBuildDisplayItems:
    def test_empty(self) -> None:
        assert build_display_items([]) == []

    def test_single_mixdepth_has_no_separator(self) -> None:
        items = build_display_items([_utxo(0), _utxo(0, txid_char="b")])
        assert None not in items
        assert len(items) == 2

    def test_separator_between_mixdepths(self) -> None:
        items = build_display_items([_utxo(0), _utxo(1), _utxo(2)])
        # u, None, u, None, u
        assert len(items) == 5
        assert items[1] is None
        assert items[3] is None

    def test_no_leading_separator(self) -> None:
        items = build_display_items([_utxo(3)])
        assert items[0] is not None


class TestSeekSelectable:
    def test_skips_separators(self) -> None:
        items = build_display_items([_utxo(0), _utxo(1)])
        # Layout: [u0, None, u1]
        assert seek_selectable(items, 1, 1, lambda _u: True) == 2
        assert seek_selectable(items, 1, -1, lambda _u: True) == 0

    def test_respects_predicate(self) -> None:
        u0, u1 = _utxo(0), _utxo(1, value=42)
        items = build_display_items([u0, u1])
        # Only the second UTXO is "selectable" for this predicate.
        assert seek_selectable(items, 0, 1, lambda u: u.value == 42) == 2

    def test_falls_back_to_opposite_direction(self) -> None:
        items = build_display_items([_utxo(0), _utxo(1)])
        last = len(items) - 1
        # Seeking forward past the end falls back to searching backwards.
        assert seek_selectable(items, last + 1, 1, lambda _u: True) == last

    def test_nothing_matches_returns_start(self) -> None:
        items = build_display_items([_utxo(0)])
        assert seek_selectable(items, 0, 1, lambda _u: False) == 0


class TestFormatAddressColumn:
    def test_repeated_address_blanked(self) -> None:
        out = format_address_column("bcrt1qsame", "bcrt1qsame")
        assert out == " " * ADDRESS_COL_WIDTH

    def test_new_address_shown(self) -> None:
        assert format_address_column("bcrt1qnew", "bcrt1qold") == "bcrt1qnew"

    def test_long_address_middle_truncated(self) -> None:
        long_addr = "bcrt1q" + "x" * 60
        out = format_address_column(long_addr, "")
        assert len(out) == ADDRESS_COL_WIDTH
        assert "..." in out
        assert out.startswith(long_addr[:20])
        assert out.endswith(long_addr[-19:])


class TestAdjustScroll:
    def test_cursor_above_view(self) -> None:
        assert adjust_scroll(2, 5, 10) == 2

    def test_cursor_below_view(self) -> None:
        assert adjust_scroll(20, 0, 10) == 11

    def test_cursor_in_view_unchanged(self) -> None:
        assert adjust_scroll(5, 3, 10) == 3
