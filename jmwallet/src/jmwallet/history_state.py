"""Durable cursor state for incremental on-chain history reconstruction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from hashlib import sha256
from pathlib import Path

from jmcore.secure_files import atomic_write_private, read_private_file
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jmwallet.backends.base import BlockchainBackend


class ReconstructionCheckpoint(BaseModel):
    """A completed reconstruction baseline and its backend cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = 1
    wallet_fingerprint: str
    network: str
    backend_id: str
    cursor: str | None = None
    regular_branch_ends: dict[str, int] = Field(default_factory=dict)
    scanned_address_hashes: set[str] = Field(default_factory=set)


def _backend_id(backend: BlockchainBackend) -> str:
    state_id = getattr(backend, "get_history_state_id", None)
    if callable(state_id):
        return str(state_id())
    backend_type = type(backend)
    return f"{backend_type.__module__}.{backend_type.__qualname__}"


def _checkpoint_path(data_dir: Path, wallet_fingerprint: str) -> Path:
    safe_fingerprint = wallet_fingerprint.strip().lower()
    if not safe_fingerprint or any(c not in "0123456789abcdef" for c in safe_fingerprint):
        raise ValueError("wallet fingerprint must contain only hexadecimal characters")
    return data_dir / "state" / f"history_reconstruction_{safe_fingerprint}.json"


def _address_hash(address: str) -> str:
    return sha256(address.strip().lower().encode("ascii")).hexdigest()


def load_reconstruction_cursor(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
) -> str | None:
    """Load a matching completed baseline, falling back safely on any mismatch."""
    try:
        path = _checkpoint_path(data_dir, wallet_fingerprint)
    except ValueError as exc:
        logger.warning(f"Ignoring history reconstruction checkpoint: {exc}")
        return None
    if not path.exists():
        return None

    try:
        checkpoint = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
    except (OSError, ValidationError, ValueError) as exc:
        logger.warning(f"Ignoring invalid history reconstruction checkpoint {path}: {exc}")
        return None

    if (
        checkpoint.version != 1
        or checkpoint.wallet_fingerprint != wallet_fingerprint
        or checkpoint.network != network
        or checkpoint.backend_id != _backend_id(backend)
    ):
        logger.debug(f"Ignoring mismatched history reconstruction checkpoint {path}")
        return None
    return checkpoint.cursor


def has_reconstruction_address_coverage(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    mixdepth_count: int,
    range_end: int,
) -> bool:
    """Return whether a completed baseline covered every initial regular branch."""
    try:
        path = _checkpoint_path(data_dir, wallet_fingerprint)
        checkpoint = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
    except (OSError, ValidationError, ValueError):
        return False
    if (
        checkpoint.version != 1
        or checkpoint.wallet_fingerprint != wallet_fingerprint
        or checkpoint.network != network
        or checkpoint.backend_id != _backend_id(backend)
    ):
        return False
    return all(
        checkpoint.regular_branch_ends.get(f"{mixdepth}:{change}", -1) >= range_end
        for mixdepth in range(mixdepth_count)
        for change in (0, 1)
    )


def has_reconstruction_branch_coverage(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    mixdepth: int,
    change: int,
    range_end: int,
) -> bool:
    """Return whether one regular branch was historically scanned through an index."""
    try:
        path = _checkpoint_path(data_dir, wallet_fingerprint)
        checkpoint = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
    except (OSError, ValidationError, ValueError):
        return False
    return (
        checkpoint.version == 1
        and checkpoint.wallet_fingerprint == wallet_fingerprint
        and checkpoint.network == network
        and checkpoint.backend_id == _backend_id(backend)
        and checkpoint.regular_branch_ends.get(f"{mixdepth}:{change}", -1) >= range_end
    )


def save_reconstruction_cursor(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    cursor: str,
    address_paths: Mapping[str, tuple[int, int, int]] | None = None,
) -> None:
    """Atomically persist a cursor after all corresponding rows are durable."""
    if not cursor:
        return
    regular_branch_ends: dict[str, int] = {}
    for mixdepth, change, index in (address_paths or {}).values():
        if change not in (0, 1):
            continue
        key = f"{mixdepth}:{change}"
        regular_branch_ends[key] = max(regular_branch_ends.get(key, -1), index)
    existing_coverage: dict[str, int] = {}
    existing_address_hashes: set[str] = set()
    try:
        existing = ReconstructionCheckpoint.model_validate_json(
            read_private_file(_checkpoint_path(data_dir, wallet_fingerprint))
        )
        if (
            existing.wallet_fingerprint == wallet_fingerprint
            and existing.network == network
            and existing.backend_id == _backend_id(backend)
        ):
            existing_coverage = existing.regular_branch_ends
            existing_address_hashes = existing.scanned_address_hashes
    except (OSError, ValidationError, ValueError):
        pass
    for key, index in existing_coverage.items():
        regular_branch_ends[key] = max(regular_branch_ends.get(key, -1), index)
    checkpoint = ReconstructionCheckpoint(
        wallet_fingerprint=wallet_fingerprint,
        network=network,
        backend_id=_backend_id(backend),
        cursor=cursor,
        regular_branch_ends=regular_branch_ends,
        scanned_address_hashes=existing_address_hashes,
    )
    path = _checkpoint_path(data_dir, wallet_fingerprint)
    atomic_write_private(path, checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n")


def record_reconstruction_address_coverage(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    branch_ends: Mapping[str, int],
) -> None:
    """Persist regular branches that completed historical scanning."""
    path = _checkpoint_path(data_dir, wallet_fingerprint)
    cursor: str | None = None
    regular_branch_ends: dict[str, int] = {}
    scanned_address_hashes: set[str] = set()
    try:
        existing = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
        if (
            existing.wallet_fingerprint == wallet_fingerprint
            and existing.network == network
            and existing.backend_id == _backend_id(backend)
        ):
            cursor = existing.cursor
            regular_branch_ends.update(existing.regular_branch_ends)
            scanned_address_hashes.update(existing.scanned_address_hashes)
    except (OSError, ValidationError, ValueError):
        pass
    for key, index in branch_ends.items():
        regular_branch_ends[key] = max(regular_branch_ends.get(key, -1), index)
    checkpoint = ReconstructionCheckpoint(
        wallet_fingerprint=wallet_fingerprint,
        network=network,
        backend_id=_backend_id(backend),
        cursor=cursor,
        regular_branch_ends=regular_branch_ends,
        scanned_address_hashes=scanned_address_hashes,
    )
    atomic_write_private(path, checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n")


def get_uncovered_reconstruction_addresses(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    addresses: Iterable[str],
) -> list[str]:
    """Return explicit addresses without durable historical-scan coverage."""
    unique_addresses = list(dict.fromkeys(address.strip().lower() for address in addresses))
    try:
        checkpoint = ReconstructionCheckpoint.model_validate_json(
            read_private_file(_checkpoint_path(data_dir, wallet_fingerprint))
        )
    except (OSError, ValidationError, ValueError):
        return unique_addresses
    if (
        checkpoint.version != 1
        or checkpoint.wallet_fingerprint != wallet_fingerprint
        or checkpoint.network != network
        or checkpoint.backend_id != _backend_id(backend)
    ):
        return unique_addresses
    return [
        address
        for address in unique_addresses
        if _address_hash(address) not in checkpoint.scanned_address_hashes
    ]


def record_reconstruction_explicit_address_coverage(
    data_dir: Path,
    *,
    wallet_fingerprint: str,
    network: str,
    backend: BlockchainBackend,
    addresses: Iterable[str],
) -> None:
    """Persist explicit addresses that completed historical scanning."""
    path = _checkpoint_path(data_dir, wallet_fingerprint)
    cursor: str | None = None
    regular_branch_ends: dict[str, int] = {}
    scanned_address_hashes: set[str] = set()
    try:
        existing = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
        if (
            existing.wallet_fingerprint == wallet_fingerprint
            and existing.network == network
            and existing.backend_id == _backend_id(backend)
        ):
            cursor = existing.cursor
            regular_branch_ends.update(existing.regular_branch_ends)
            scanned_address_hashes.update(existing.scanned_address_hashes)
    except (OSError, ValidationError, ValueError):
        pass
    scanned_address_hashes.update(_address_hash(address) for address in addresses)
    checkpoint = ReconstructionCheckpoint(
        wallet_fingerprint=wallet_fingerprint,
        network=network,
        backend_id=_backend_id(backend),
        cursor=cursor,
        regular_branch_ends=regular_branch_ends,
        scanned_address_hashes=scanned_address_hashes,
    )
    atomic_write_private(path, checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n")


def clear_reconstruction_cursor(data_dir: Path, *, wallet_fingerprint: str) -> None:
    """Invalidate incremental state before rebuilding or widening coverage."""
    path: Path | None = None
    try:
        path = _checkpoint_path(data_dir, wallet_fingerprint)
        if not path.exists():
            return
        checkpoint = ReconstructionCheckpoint.model_validate_json(read_private_file(path))
        checkpoint = checkpoint.model_copy(update={"cursor": None})
        atomic_write_private(path, checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n")
    except (OSError, ValidationError, ValueError) as exc:
        try:
            if path is not None:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        logger.warning(f"Could not clear history reconstruction checkpoint: {exc}")
