"""
Tests for the standard transaction confirmation display (issue #107).

Verifies that the SEND confirmation summary follows the workflow ordering:
Source Mixdepth, Destination, Amount, Change, Miner Fee Rate, Miner Fee.
"""

from __future__ import annotations

import pytest

from jmcore.confirmation import (
    _display_coinjoin_send_confirmation,
    _display_standard_send_confirmation,
    format_maker_summary,
)


@pytest.fixture
def send_capture(capsys: pytest.CaptureFixture[str]) -> pytest.CaptureFixture[str]:
    """Render a representative SEND confirmation matching jm-wallet send."""
    _display_standard_send_confirmation(
        operation="send",
        amount=79_456,
        destination="bc1qexampledestination",
        fee=None,
        mining_fee=333,
        additional_info={
            "Source Mixdepth": 2,
            "Change": "19,422 sats (0.00019422 BTC)",
            "Miner Fee Rate": "1.20 sat/vB",
        },
    )
    return capsys


def test_header_uses_mixed_case(send_capture: pytest.CaptureFixture[str]) -> None:
    """Header reads 'Expected SEND Transaction', not legacy all-caps."""
    out = send_capture.readouterr().out
    assert "Expected SEND Transaction" in out
    assert "TRANSACTION CONFIRMATION" not in out


def test_field_order_follows_workflow(send_capture: pytest.CaptureFixture[str]) -> None:
    """Fields appear in the order proposed in issue #107."""
    out = send_capture.readouterr().out
    expected_order = [
        "Source Mixdepth:",
        "Destination:",
        "Amount:",
        "Change:",
        "Miner Fee Rate:",
        "Miner Fee:",
    ]
    positions = [out.index(label) for label in expected_order]
    assert positions == sorted(positions), f"unexpected order in output:\n{out}"


def test_fee_label_renamed_to_miner_fee(send_capture: pytest.CaptureFixture[str]) -> None:
    """The plain 'Fee:' label is replaced with 'Miner Fee:' for SEND."""
    out = send_capture.readouterr().out
    # 'Miner Fee:' must appear; bare 'Fee:' (not preceded by 'Miner ') must not.
    assert "Miner Fee:" in out
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("Fee:"):
            raise AssertionError(f"unexpected bare 'Fee:' label: {line!r}")


def test_sweep_renders_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    """A zero amount is rendered as a SWEEP rather than '0 sats'."""
    _display_standard_send_confirmation(
        operation="send",
        amount=0,
        destination="bc1qexampledestination",
        fee=200,
        mining_fee=None,
        additional_info={"Source Mixdepth": 0},
    )
    out = capsys.readouterr().out
    assert "SWEEP" in out


def test_internal_destination_label(capsys: pytest.CaptureFixture[str]) -> None:
    """INTERNAL destination is rendered with the next-mixdepth hint."""
    _display_standard_send_confirmation(
        operation="send",
        amount=10_000,
        destination="INTERNAL",
        fee=100,
        mining_fee=None,
        additional_info={"Source Mixdepth": 1},
    )
    out = capsys.readouterr().out
    assert "INTERNAL (next mixdepth)" in out


def test_unknown_additional_info_keys_still_render(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Forward-compatibility: unknown additional_info keys are not dropped."""
    _display_standard_send_confirmation(
        operation="send",
        amount=1_000,
        destination="bc1qexample",
        fee=50,
        mining_fee=None,
        additional_info={"Custom Note": "hello world"},
    )
    out = capsys.readouterr().out
    assert "Custom Note:" in out
    assert "hello world" in out


def test_coinjoin_fee_amounts_include_percentages(capsys: pytest.CaptureFixture[str]) -> None:
    """CoinJoin fees are shown relative to the CoinJoin amount."""
    makers = format_maker_summary(
        [
            {"nick": "maker-one", "fee": 100, "bond_value": 0},
            {"nick": "maker-two", "fee": 232, "bond_value": 0},
        ],
        amount=100_000,
    )
    _display_coinjoin_send_confirmation(
        amount=100_000,
        destination="bc1qexampledestination",
        mining_fee=50,
        additional_info=makers,
    )

    out = capsys.readouterr().out

    assert "maker-one: 100 sats (0.1000%)" in out
    assert "maker-two: 232 sats (0.2320%)" in out
    assert "Total Maker Fee:  332 sats (0.3320%)" in out
    assert "Miner Fee:        50 sats (0.00000050 BTC) (0.0500%)" in out
    assert "Total Fee:        382 sats (0.00000382 BTC) (0.3820%)" in out


def test_coinjoin_zero_fee_percentage_and_sweep_amount(capsys: pytest.CaptureFixture[str]) -> None:
    """Zero fees include a percentage, but sweeps do not divide by zero."""
    makers = format_maker_summary(
        [{"nick": "maker-zero", "fee": 0, "bond_value": 0}],
        amount=100_000,
    )
    _display_coinjoin_send_confirmation(
        amount=100_000,
        destination="bc1qexampledestination",
        mining_fee=0,
        additional_info=makers,
    )
    out = capsys.readouterr().out
    assert "maker-zero: 0 sats (0.0000%)" in out
    assert "Total Maker Fee:  0 sats (0.0000%)" in out
    assert "Miner Fee:        0 sats (0.00000000 BTC) (0.0000%)" in out
    assert "Total Fee:        0 sats (0.00000000 BTC) (0.0000%)" in out

    sweep_makers = format_maker_summary(
        [{"nick": "maker-sweep", "fee": 100, "bond_value": 0}],
        amount=0,
    )
    _display_coinjoin_send_confirmation(
        amount=0,
        destination="bc1qexampledestination",
        mining_fee=50,
        additional_info=sweep_makers,
    )
    sweep_out = capsys.readouterr().out
    assert "maker-sweep: 100 sats [no bond]" in sweep_out
    assert "%" not in sweep_out


def test_format_maker_summary_without_amount_remains_compatible() -> None:
    """Existing callers can omit the CoinJoin amount."""
    summary = format_maker_summary(
        [{"nick": "maker", "fee": 232, "bond_value": 0}],
        fee_rate=1.5,
    )

    assert summary["Makers"] == ["maker: 232 sats [no bond]"]
    assert summary["Fee Rate"] == 1.5
