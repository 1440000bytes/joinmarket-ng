"""Tests for labels shown by direct-send interactive UTXO selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from jmwallet.cli.send import _select_input_utxos
from jmwallet.wallet.models import UTXOInfo


def _utxo(*, label: str | None = None, locktime: int | None = None) -> UTXOInfo:
    return UTXOInfo(
        txid="a" * 64,
        vout=0,
        value=100_000,
        address="bcrt1qselectorlabel",
        confirmations=6,
        scriptpubkey="0014" + "00" * 20,
        path="m/84'/1'/0'/0/0",
        mixdepth=0,
        label=label,
        locktime=locktime,
    )


@pytest.mark.asyncio
async def test_selector_preserves_user_and_fidelity_bond_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct-send selection does not replace existing BIP-329 annotations."""
    user_labeled = _utxo(label="personal note")
    fidelity_bond = _utxo(label="bond note", locktime=1_900_000_000)
    wallet = AsyncMock()
    wallet.mixdepth_count = 1
    wallet.get_utxos = AsyncMock(return_value=[user_labeled, fidelity_bond])
    wallet.get_utxo_label_from_wallet = Mock(return_value="cj-out")

    captured: list[UTXOInfo] = []

    def fake_select(utxos, *_args, **_kwargs):  # noqa: ANN001, ANN202
        captured.extend(utxos)
        return [user_labeled]

    import jmwallet.utxo_selector

    monkeypatch.setattr(jmwallet.utxo_selector, "select_utxos_interactive", fake_select)

    selected = await _select_input_utxos(
        wallet=wallet,
        backend_settings=Mock(),
        amount=50_000,
        mixdepth=None,
        interactive=True,
    )

    assert selected == ([user_labeled], 0)
    assert [utxo.label for utxo in captured] == ["personal note", "bond note"]
    wallet.get_utxo_label_from_wallet.assert_not_called()


@pytest.mark.asyncio
async def test_selector_classifies_unlabeled_regular_utxo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct-send selection classifies an unlabeled regular UTXO."""
    unlabeled = _utxo()
    wallet = AsyncMock()
    wallet.mixdepth_count = 1
    wallet.get_utxos = AsyncMock(return_value=[unlabeled])
    wallet.get_utxo_label_from_wallet = Mock(return_value="cj-out")

    import jmwallet.utxo_selector

    monkeypatch.setattr(
        jmwallet.utxo_selector,
        "select_utxos_interactive",
        lambda utxos, *_args, **_kwargs: list(utxos),
    )

    selected = await _select_input_utxos(
        wallet=wallet,
        backend_settings=Mock(),
        amount=50_000,
        mixdepth=None,
        interactive=True,
    )

    assert selected == ([unlabeled], 0)
    assert unlabeled.label == "cj-out"
    wallet.get_utxo_label_from_wallet.assert_called_once_with(unlabeled.address)
