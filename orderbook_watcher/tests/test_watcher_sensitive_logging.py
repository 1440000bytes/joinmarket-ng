"""Tests for sensitive orderbook watcher log records."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock

import pytest
from jmcore.models import FidelityBond
from loguru import logger

from orderbook_watcher.aggregator import OrderbookAggregator
from orderbook_watcher.main import setup_logging


@pytest.mark.parametrize("sensitive", [False, True])
def test_custom_stderr_sink_filters_sensitive_records(
    monkeypatch: pytest.MonkeyPatch, sensitive: bool
) -> None:
    output = StringIO()
    monkeypatch.setattr("orderbook_watcher.main.sys.stderr", output)
    setup_logging("INFO", sensitive=sensitive)

    logger.info("ordinary-watcher-record")
    logger.bind(sensitive=True).info("private-watcher-record")

    rendered = output.getvalue()
    assert "ordinary-watcher-record" in rendered
    assert ("private-watcher-record" in rendered) is sensitive


@pytest.mark.asyncio
async def test_bond_outpoint_log_is_sensitive() -> None:
    aggregator = OrderbookAggregator(directory_nodes=[], network="regtest", mempool_api_url="")
    aggregator.mempool_api = AsyncMock()
    aggregator.mempool_api.get_transaction.return_value = None
    bond = FidelityBond(
        counterparty="J5maker",
        utxo_txid="a" * 64,
        utxo_vout=7,
        locktime=2_000_000_000,
        amount=0,
        script="02" + "11" * 32,
        utxo_confirmations=0,
        cert_expiry=901_152,
    )
    records: list[dict[str, object]] = []
    handler = logger.add(
        lambda message: records.append(
            {
                "message": message.record["message"],
                "sensitive": message.record["extra"].get("sensitive", False),
            }
        )
    )
    try:
        await aggregator._calculate_bond_value_single(bond, current_time=1_700_000_000)
    finally:
        logger.remove(handler)

    assert records == [
        {
            "message": f"Bond {'a' * 64}:7 not confirmed",
            "sensitive": True,
        }
    ]
