"""Taker CoinJoin log correlation tests."""

from __future__ import annotations

from types import SimpleNamespace

from loguru import logger

from taker.taker import Taker


def test_commitment_rotation_replaces_taker_log_context() -> None:
    taker = object.__new__(Taker)
    taker._coinjoin_log_context = None
    commitment = SimpleNamespace(commitment=bytes.fromhex("ab" * 32))
    taker._session = SimpleNamespace(podle_commitment=SimpleNamespace(commitment=commitment))
    records: list[dict[str, object]] = []
    handler_id = logger.add(lambda message: records.append(dict(message.record["extra"])))
    try:
        assert taker._activate_coinjoin_log_context() == "cj-abababababab"
        logger.info("first")
        taker._session.podle_commitment = SimpleNamespace(
            commitment=SimpleNamespace(commitment=bytes.fromhex("cd" * 32))
        )
        assert taker._activate_coinjoin_log_context() == "cj-cdcdcdcdcdcd"
        logger.info("second")
        taker._clear_coinjoin_log_context()
        logger.info("ordinary")
    finally:
        taker._clear_coinjoin_log_context()
        logger.remove(handler_id)

    assert records[0]["cj_id"] == "cj-abababababab"
    assert records[1]["cj_id"] == "cj-cdcdcdcdcdcd"
    assert "cj_id" not in records[2]
