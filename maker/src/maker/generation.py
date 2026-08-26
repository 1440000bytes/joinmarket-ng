"""Runtime resources owned by one maker identity generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from jmcore.crypto import NickIdentity
from jmcore.directory_client import DirectoryClient
from jmcore.models import Offer
from jmcore.network import HiddenServiceListener, TCPConnection
from jmcore.tor_control import EphemeralHiddenService, TorControlClient

from maker.direct_connection import DirectConnectionState
from maker.directory_pool import MakerDirectoryPool
from maker.offers import OfferManager


class GenerationState(StrEnum):
    """Whether a generation may accept new work."""

    ACCEPTING = "accepting"
    GRACE = "grace"
    CLOSED = "closed"


@dataclass(slots=True)
class MakerGeneration:
    """All identity-bound maker resources.

    The bot intentionally keeps current-generation aliases for compatibility,
    but protocol routing always resolves one of these records explicitly.
    """

    generation_id: int
    nick_identity: NickIdentity
    offer_manager: OfferManager
    directory_pool: MakerDirectoryPool
    directory_clients: dict[str, DirectoryClient] = field(default_factory=dict)
    current_offers: list[Offer] = field(default_factory=list)
    hidden_service_listener: HiddenServiceListener | None = None
    tor_control: TorControlClient | None = None
    ephemeral_hidden_service: EphemeralHiddenService | None = None
    onion_host: str | None = None
    listener_port: int | None = None
    direct_connections: dict[str, TCPConnection] = field(default_factory=dict)
    direct_connection_states: dict[TCPConnection, DirectConnectionState] = field(
        default_factory=dict
    )
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    reconnect_attempts: dict[str, int] = field(default_factory=dict)
    all_directories_disconnected: bool = False
    state: GenerationState = GenerationState.ACCEPTING
    grace_deadline: float | None = None
