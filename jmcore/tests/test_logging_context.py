"""Tests for CoinJoin log correlation context."""

from __future__ import annotations

import asyncio

import pytest
from loguru import logger

from jmcore.logging_context import coinjoin_id_from_commitment, coinjoin_log_context


def test_coinjoin_id_requires_full_commitment() -> None:
    assert coinjoin_id_from_commitment("AB" * 32) == "cj-abababababab"
    with pytest.raises(ValueError, match="64 hexadecimal"):
        coinjoin_id_from_commitment("ab" * 31)
    with pytest.raises(ValueError, match="64 hexadecimal"):
        coinjoin_id_from_commitment("z" * 64)


@pytest.mark.asyncio
async def test_coinjoin_context_is_task_local_and_does_not_leak() -> None:
    records: list[dict[str, object]] = []
    handler = logger.add(lambda message: records.append(dict(message.record["extra"])))
    try:

        async def emit(commitment: str) -> None:
            with coinjoin_log_context(commitment):
                await asyncio.sleep(0)
                logger.info("correlated")

        await asyncio.gather(emit("ab" * 32), emit("cd" * 32))
        logger.info("ordinary")
    finally:
        logger.remove(handler)

    assert {record.get("cj_id") for record in records[:2]} == {
        "cj-abababababab",
        "cj-cdcdcdcdcdcd",
    }
    assert "cj_id" not in records[-1]
