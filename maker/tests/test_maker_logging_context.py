"""Maker session log correlation tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from loguru import logger

from maker.maker_session import MakerSession


@pytest.mark.asyncio
async def test_session_handler_binds_commitment_context() -> None:
    session = object.__new__(MakerSession)
    session.inner = SimpleNamespace(taker_nick="taker", commitment=bytes.fromhex("ab" * 32))
    session.lock = asyncio.Lock()
    session.expired = False
    session.deadline = time.monotonic() + 1
    bot = SimpleNamespace(active_sessions={"taker": session})
    records: list[dict[str, object]] = []
    handler_id = logger.add(lambda message: records.append(dict(message.record["extra"])))
    try:

        async def handler() -> None:
            logger.info("maker handler")

        await session.run_handler(bot, handler)
    finally:
        logger.remove(handler_id)

    assert records[-1]["cj_id"] == "cj-abababababab"
