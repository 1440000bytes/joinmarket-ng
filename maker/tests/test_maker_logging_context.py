"""Maker session log correlation tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from loguru import logger

from maker.coinjoin import CoinJoinState
from maker.maker_session import MakerSession
from maker.session_logging import log_coinjoin_message


@pytest.mark.asyncio
async def test_session_handler_binds_commitment_context() -> None:
    session = object.__new__(MakerSession)
    session.inner = SimpleNamespace(taker_nick="taker", commitment=bytes.fromhex("ab" * 32))
    session.generation_id = 0
    session.lock = asyncio.Lock()
    session.expired = False
    session.deadline = time.monotonic() + 1
    bot = SimpleNamespace(active_sessions={(0, "taker"): session})
    records: list[dict[str, object]] = []
    handler_id = logger.add(lambda message: records.append(dict(message.record["extra"])))
    try:

        async def handler() -> None:
            logger.info("maker handler")

        await session.run_handler(bot, handler)
    finally:
        logger.remove(handler_id)

    assert records[-1]["cj_id"] == "cj-abababababab"


def test_coinjoin_message_event_is_structured_and_payload_free() -> None:
    records: list[dict[str, object]] = []
    handler_id = logger.add(lambda message: records.append(dict(message.record)), level="DEBUG")
    try:
        log_coinjoin_message(
            "received",
            "!auth",
            peer="J5Taker",
            transport="directory:test",
            payload_length=406,
            state="pubkey_sent",
        )
    finally:
        logger.remove(handler_id)

    record = records[-1]
    extra = record["extra"]
    assert isinstance(extra, dict)
    assert extra == {
        "cj_event": True,
        "direction": "received",
        "command": "auth",
        "peer": "J5Taker",
        "transport": "directory:test",
        "payload_length": 406,
        "state": "pubkey_sent",
        "outcome": "accepted",
        "deliveries": None,
    }
    assert "406" in str(record["message"])
    assert "ciphertext" not in str(record["message"])


@pytest.mark.asyncio
async def test_406_byte_auth_message_logs_only_normalized_metadata() -> None:
    inner = SimpleNamespace(
        taker_nick="J5Taker",
        commitment=bytes.fromhex("ab" * 32),
        state=CoinJoinState.PUBKEY_SENT,
        session_timeout_sec=60,
        crypto=SimpleNamespace(is_encrypted=False),
        validate_channel=lambda _source: True,
    )
    session = MakerSession(inner)
    bot = SimpleNamespace(active_sessions={(0, "J5Taker"): session})
    auth_message = "auth " + "a" * 401
    assert len(auth_message.encode("utf-8")) == 406

    records: list[dict[str, object]] = []
    handler_id = logger.add(
        lambda message: records.append(dict(message.record["extra"])), level="DEBUG"
    )
    try:
        await session.on_auth(bot, auth_message, "directory:test")
    finally:
        logger.remove(handler_id)

    event = next(record for record in records if record.get("command") == "auth")
    assert event["payload_length"] == 406
    assert event["state"] == "pubkey_sent"
    assert auth_message not in str(event)
