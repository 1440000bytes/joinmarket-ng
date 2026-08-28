"""Interactive transaction confirmation behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from jmcore import confirmation


@pytest.mark.asyncio
async def test_async_confirmation_reads_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    add_reader = MagicMock()
    remove_reader = MagicMock(return_value=True)
    stdin = MagicMock()
    stdin.fileno.return_value = 17
    stdin.readline.return_value = "yes\n"
    monkeypatch.setattr(confirmation, "_prepare_confirmation", MagicMock(return_value=True))
    monkeypatch.setattr(confirmation.sys, "stdin", stdin)
    monkeypatch.setattr(loop, "add_reader", add_reader)
    monkeypatch.setattr(loop, "remove_reader", remove_reader)

    task = asyncio.create_task(confirmation.confirm_transaction_async("coinjoin", 1_000))
    await asyncio.sleep(0)
    read_ready = add_reader.call_args.args[1]
    read_ready()

    assert await task is True
    remove_reader.assert_called_once_with(17)


@pytest.mark.asyncio
async def test_async_confirmation_cancellation_removes_stdin_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    add_reader = MagicMock()
    remove_reader = MagicMock(return_value=True)
    stdin = MagicMock()
    stdin.fileno.return_value = 19
    monkeypatch.setattr(confirmation, "_prepare_confirmation", MagicMock(return_value=True))
    monkeypatch.setattr(confirmation.sys, "stdin", stdin)
    monkeypatch.setattr(loop, "add_reader", add_reader)
    monkeypatch.setattr(loop, "remove_reader", remove_reader)

    task = asyncio.create_task(confirmation.confirm_transaction_async("coinjoin", 1_000))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    remove_reader.assert_called_once_with(19)


@pytest.mark.asyncio
async def test_async_confirmation_falls_back_when_loop_cannot_watch_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    stdin = MagicMock()
    stdin.fileno.return_value = 23
    monkeypatch.setattr(confirmation, "_prepare_confirmation", MagicMock(return_value=True))
    monkeypatch.setattr(confirmation.sys, "stdin", stdin)
    monkeypatch.setattr(loop, "add_reader", MagicMock(side_effect=NotImplementedError))
    read_response = MagicMock(return_value=True)
    monkeypatch.setattr(confirmation, "_read_confirmation_response", read_response)

    assert await confirmation.confirm_transaction_async("coinjoin", 1_000) is True
    read_response.assert_called_once_with()
