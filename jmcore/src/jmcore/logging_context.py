"""Task-local CoinJoin log correlation helpers."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager

from loguru import logger

_COMMITMENT_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def coinjoin_id_from_commitment(commitment: str) -> str:
    """Derive the stable, short log ID for a validated PoDLE commitment."""
    if not _COMMITMENT_RE.fullmatch(commitment):
        raise ValueError("PoDLE commitment must be exactly 64 hexadecimal characters")
    return f"cj-{commitment[:12].lower()}"


def coinjoin_log_context(commitment: str) -> AbstractContextManager[None]:
    """Bind a commitment-derived CoinJoin ID to Loguru's task-local context."""
    return logger.contextualize(cj_id=coinjoin_id_from_commitment(commitment))
