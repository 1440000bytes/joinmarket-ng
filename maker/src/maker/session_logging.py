"""Structured maker CoinJoin session logging."""

from __future__ import annotations

from typing import Literal

from loguru import logger

CoinJoinMessageDirection = Literal["received", "sent"]


def log_coinjoin_message(
    direction: CoinJoinMessageDirection,
    command: str,
    *,
    peer: str,
    transport: str,
    payload_length: int,
    state: str,
    outcome: str = "accepted",
    deliveries: int | None = None,
) -> None:
    """Log one payload-free CoinJoin protocol message event at DEBUG."""
    normalized_command = command.lstrip("!")
    details = (
        f"CoinJoin message {direction}: command=!{normalized_command}, peer={peer}, "
        f"transport={transport}, payload_len={payload_length}, state={state}, outcome={outcome}"
    )
    if deliveries is not None:
        details += f", deliveries={deliveries}"
    logger.bind(
        cj_event=True,
        direction=direction,
        command=normalized_command,
        peer=peer,
        transport=transport,
        payload_length=payload_length,
        state=state,
        outcome=outcome,
        deliveries=deliveries,
    ).debug(details)
