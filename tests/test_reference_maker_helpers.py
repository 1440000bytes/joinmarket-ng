"""Unit tests for reference-maker E2E process helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from tests.e2e import test_reference_maker_our_taker as reference_maker


def test_yieldgenerator_readiness_allows_late_directory_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JAM can connect just after logging its internal directory deadline."""
    outputs = iter(
        [
            "failed to connect and handshake with any directories",
            "failed to connect and handshake with any directories\n"
            "all message channels connected",
        ]
    )
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = None
    monkeypatch.setattr(
        reference_maker,
        "get_yieldgenerator_logs",
        lambda _maker_id: next(outputs),
    )
    monkeypatch.setattr(reference_maker.time, "sleep", lambda _seconds: None)

    assert reference_maker.wait_for_yieldgenerator_ready(2, process, timeout=1)
