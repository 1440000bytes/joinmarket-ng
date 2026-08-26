"""Focused tests for maker identity generation ownership and cutover."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jmcore.bitcoin import get_txid
from jmcore.crypto import NickIdentity
from jmcore.directory_client import DirectoryClientError
from jmcore.models import NetworkType
from jmcore.protocol import JM_VERSION, MessageType

from maker.bot import MakerBot
from maker.coinjoin import CoinJoinState
from maker.config import MakerConfig
from maker.directory_pool import MakerDirectoryPool
from maker.generation import GenerationState, MakerGeneration
from maker.maker_session import MakerSession, PendingSignedRound
from maker.offers import OfferManager


@pytest.fixture
def config() -> MakerConfig:
    return MakerConfig(
        mnemonic="test " * 12,
        network=NetworkType.REGTEST,
        directory_servers=["directory.onion:5222"],
        stream_isolation=True,
        identity_renewal_min_sec=60,
        identity_renewal_max_sec=120,
        identity_grace_sec=60,
    )


@pytest.fixture
def bot(config: MakerConfig) -> MakerBot:
    backend = MagicMock()
    backend.can_provide_neutrino_metadata.return_value = False
    wallet = MagicMock()
    return MakerBot(wallet=wallet, backend=backend, config=config)


def _generation(bot: MakerBot, generation_id: int) -> MakerGeneration:
    identity = NickIdentity(JM_VERSION)
    pool = MakerDirectoryPool(
        config=bot.config,
        nick_identity=identity,
        neutrino_compat=False,
        onion_host=f"generation-{generation_id}.onion",
        onion_serving_port=bot.config.onion_serving_port,
    )
    manager = OfferManager(bot.wallet, bot.config, identity.nick)
    generation = MakerGeneration(
        generation_id=generation_id,
        nick_identity=identity,
        offer_manager=manager,
        directory_pool=pool,
    )
    pool.clients = generation.directory_clients
    return generation


@pytest.mark.parametrize("stream_isolation", [False, True])
def test_generation_pools_use_distinct_stable_tor_credentials(
    config: MakerConfig, stream_isolation: bool
) -> None:
    config = config.model_copy(update={"stream_isolation": stream_isolation})
    first = MakerDirectoryPool(
        config=config,
        nick_identity=NickIdentity(JM_VERSION),
        neutrino_compat=False,
    )
    second = MakerDirectoryPool(
        config=config,
        nick_identity=NickIdentity(JM_VERSION),
        neutrino_compat=False,
    )

    assert first._dir_creds != second._dir_creds
    first_kwargs = first._build_client_kwargs("directory.onion", 5222)
    repeated_kwargs = first._build_client_kwargs("directory.onion", 5222)
    assert first_kwargs["socks_username"] == repeated_kwargs["socks_username"]
    assert first_kwargs["socks_password"] == repeated_kwargs["socks_password"]
    assert first_kwargs["socks_password"] == first._dir_creds[1]


def test_generations_own_distinct_identity_and_mutable_state(bot: MakerBot) -> None:
    first = bot.generations[0]
    second = _generation(bot, 1)

    assert first.nick_identity is not second.nick_identity
    assert first.nick_identity.nick != second.nick_identity.nick
    assert first.offer_manager is not second.offer_manager
    assert first.directory_pool is not second.directory_pool
    assert first.directory_clients is not second.directory_clients
    assert first.current_offers is not second.current_offers
    assert first.direct_connections is not second.direct_connections
    assert first.direct_connection_states is not second.direct_connection_states


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active,bonded", [(False, False), (False, True), (True, False), (True, True)]
)
async def test_scheduler_samples_independently_of_activity(
    bot: MakerBot, active: bool, bonded: bool
) -> None:
    bot.running = True
    bot.fidelity_bond = MagicMock() if bonded else None
    if active:
        bot.active_sessions[(0, "J5Active")] = MagicMock()
    bot.current_offers = [MagicMock()]
    samples: list[tuple[int, int]] = []

    sleep_count = 0

    async def sleep(delay: float) -> None:
        nonlocal sleep_count
        samples.append((bot.config.identity_renewal_min_sec, bot.config.identity_renewal_max_sec))
        assert delay == 73.0
        sleep_count += 1
        if sleep_count == 2:
            bot.running = False

    with (
        patch("maker.bot.secure_random.uniform", return_value=73.0),
        patch("maker.bot.asyncio.sleep", new=AsyncMock(side_effect=sleep)),
        patch.object(bot, "_rotate_generation", new=AsyncMock(return_value=True)) as rotate,
    ):
        await bot._identity_renewal_scheduler()

    assert samples == [(60, 120), (60, 120)]
    rotate.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cutover_retains_old_direct_routes_and_uses_new_generation(bot: MakerBot) -> None:
    old = bot.generations[0]
    old.current_offers = [MagicMock(oid=0), MagicMock(oid=1)]
    bot.current_offers = old.current_offers
    old_client = MagicMock()
    old_client.send_public_message = AsyncMock()
    old.directory_clients["directory:5222"] = old_client
    old_connection = MagicMock()
    old.direct_connections["J5SameTaker"] = old_connection
    old.hidden_service_listener = MagicMock()
    old.hidden_service_listener.stop = AsyncMock()
    replacement = _generation(bot, 1)
    new_connection = MagicMock()
    replacement.direct_connections["J5SameTaker"] = new_connection
    bot.running = True

    with (
        patch.object(
            bot, "_create_replacement_generation", new=AsyncMock(return_value=replacement)
        ),
        patch.object(bot, "_announce_generation_offers", new=AsyncMock()),
        patch.object(bot, "_start_generation_listeners"),
        patch("maker.bot.spawn_task", side_effect=lambda coroutine: coroutine.close()),
    ):
        assert await bot._rotate_generation() is True

    assert bot.current_generation_id == 1
    assert old.state is GenerationState.GRACE
    assert old.direct_connections["J5SameTaker"] is old_connection
    assert bot.direct_connections["J5SameTaker"] is new_connection
    old.hidden_service_listener.stop.assert_awaited_once_with()
    assert [call.args[0] for call in old_client.send_public_message.await_args_list] == [
        "cancel 0",
        "cancel 1",
    ]
    for task in old.tasks:
        task.cancel()
    await asyncio.gather(*old.tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_old_fill_rejected_while_same_taker_can_fill_new_generation(bot: MakerBot) -> None:
    taker_nick = "J5SameTaker"
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old.grace_deadline = time.monotonic() + 60
    old_session = MagicMock()
    bot.active_sessions[(0, taker_nick)] = old_session

    replacement = _generation(bot, 1)
    offer = MagicMock()
    offer.oid = 0
    offer.ordertype.value = "sw0reloffer"
    replacement.current_offers = [offer]
    replacement.offer_manager = MagicMock()
    replacement.offer_manager.get_offer_by_id.return_value = offer
    replacement.offer_manager.validate_offer_fill.return_value = (True, "")
    bot.generations[1] = replacement
    bot._activate_generation(replacement)

    inner = MagicMock()
    inner.taker_nick = taker_nick
    inner.session_timeout_sec = 300
    inner.state = CoinJoinState.PUBKEY_SENT
    inner.validate_channel.return_value = True
    inner.handle_fill = AsyncMock(return_value=(True, {"nacl_pubkey": "abc123", "features": []}))

    with (
        patch("maker.protocol_handlers.CoinJoinSession", return_value=inner) as session_class,
        patch("maker.protocol_handlers.check_commitment", return_value=True),
        patch.object(bot, "_initialize_minimum_fee_policy", new=AsyncMock()),
        patch.object(bot, "_send_response", new=AsyncMock()) as send_response,
    ):
        await bot._handle_fill(
            taker_nick,
            f"fill 0 500000 taker_pk P{'ab' * 32}",
            generation_id=0,
        )
        session_class.assert_not_called()

        await bot._handle_fill(
            taker_nick,
            f"fill 0 500000 taker_pk P{'cd' * 32}",
            generation_id=1,
        )

    assert bot.active_sessions[(0, taker_nick)] is old_session
    assert isinstance(bot.active_sessions[(1, taker_nick)], MakerSession)
    send_response.assert_awaited_once()
    assert send_response.await_args is not None
    assert send_response.await_args.kwargs["generation_id"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["_handle_auth", "_handle_tx"])
async def test_old_continuation_dispatches_only_to_old_session(
    bot: MakerBot, handler_name: str
) -> None:
    taker_nick = "J5PinnedTaker"
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old.grace_deadline = time.monotonic() + 60
    old_session = MagicMock()
    bot.active_sessions[(0, taker_nick)] = old_session
    replacement = _generation(bot, 1)
    bot.generations[1] = replacement
    bot._activate_generation(replacement)

    dispatch = AsyncMock()
    with patch.object(bot, "_dispatch_session_handler", new=dispatch):
        await getattr(bot, handler_name)(taker_nick, "command payload", generation_id=1)
        dispatch.assert_not_awaited()

        await getattr(bot, handler_name)(taker_nick, "command payload", generation_id=0)

    assert dispatch.await_count == 1
    assert dispatch.await_args is not None
    assert dispatch.await_args.args[0] is old_session


@pytest.mark.asyncio
async def test_old_session_response_uses_only_old_clients(bot: MakerBot) -> None:
    taker_nick = "J5PinnedResponse"
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old.grace_deadline = time.monotonic() + 60
    old_client = MagicMock()
    old_client.send_private_message = AsyncMock()
    old.directory_clients["old:5222"] = old_client

    replacement = _generation(bot, 1)
    new_client = MagicMock()
    new_client.send_private_message = AsyncMock()
    replacement.directory_clients["new:5222"] = new_client
    bot.generations[1] = replacement
    bot._activate_generation(replacement)

    inner = MagicMock()
    inner.taker_nick = taker_nick
    inner.session_timeout_sec = 300
    inner.state = CoinJoinState.AUTH_RECEIVED
    inner.crypto.encrypt.return_value = "ciphertext"
    session = MakerSession(inner, generation_id=0)
    bot.active_sessions[(0, taker_nick)] = session

    sent = await session.send_response(
        bot,
        "ioauth",
        {
            "utxo_list": "ab:0",
            "auth_pub": "pubkey",
            "cj_addr": "bcrt1qcj",
            "change_addr": "bcrt1qchange",
            "btc_sig": "signature",
        },
    )

    assert sent is True
    old_client.send_private_message.assert_awaited_once()
    new_client.send_private_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_push_is_generation_pinned_during_grace(bot: MakerBot) -> None:
    taker_nick = "J5PinnedPush"
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old.grace_deadline = time.monotonic() + 60
    replacement = _generation(bot, 1)
    bot.generations[1] = replacement
    bot._activate_generation(replacement)

    tx_bytes = bytes.fromhex("01000000000000000000")
    txid = get_txid(tx_bytes.hex())
    key = (0, taker_nick, txid)
    bot._pending_signed_rounds[key] = PendingSignedRound(
        generation_id=0,
        taker_nick=taker_nick,
        txid=txid,
        input_lock_owner="round-owner",
        outpoints=frozenset({("ab" * 32, 0)}),
        expires_at=time.monotonic() + 60,
        lock_ttl_sec=3600,
    )
    bot.wallet.renew_coinjoin_inputs.return_value = True
    bot.backend.broadcast_transaction = AsyncMock(return_value=txid)
    message = f"push {base64.b64encode(tx_bytes).decode('ascii')}"

    await bot._handle_push(taker_nick, message, generation_id=1)
    assert key in bot._pending_signed_rounds
    bot.backend.broadcast_transaction.assert_not_awaited()

    await bot._handle_push(taker_nick, message, generation_id=0)
    assert key not in bot._pending_signed_rounds
    bot.backend.broadcast_transaction.assert_awaited_once_with(tx_bytes.hex())


def test_dynamic_pool_advertises_virtual_onion_port(bot: MakerBot) -> None:
    generation = _generation(bot, 1)
    generation.listener_port = 49152
    kwargs = generation.directory_pool._build_client_kwargs("directory.onion", 5222)

    assert kwargs["location"] == f"generation-1.onion:{bot.config.onion_serving_port}"
    assert str(generation.listener_port) not in kwargs["location"]


@pytest.mark.asyncio
async def test_direct_handshake_advertises_virtual_onion_port(bot: MakerBot) -> None:
    generation = _generation(bot, 1)
    generation.onion_host = "generation-1.onion"
    generation.listener_port = 49152
    bot.generations[1] = generation
    bot._activate_generation(generation)
    connection = MagicMock()
    connection.send = AsyncMock()
    handshake = {
        "type": MessageType.HANDSHAKE.value,
        "line": json.dumps({"nick": "J5Peer", "network": "regtest"}),
    }

    handled = await bot._try_handle_handshake(
        connection, json.dumps(handshake).encode(), "peer", generation_id=1
    )

    assert handled is True
    response = json.loads(connection.send.await_args.args[0].decode())
    response_data = json.loads(response["line"])
    assert response_data["location-string"] == (
        f"generation-1.onion:{bot.config.onion_serving_port}"
    )
    assert str(generation.listener_port) not in response_data["location-string"]


@pytest.mark.asyncio
async def test_grace_cleanup_closes_only_old_generation(bot: MakerBot) -> None:
    old = bot.generations[0]
    current = _generation(bot, 1)
    old.state = GenerationState.GRACE
    old.grace_deadline = time.monotonic()
    old_client = MagicMock()
    old_client.close = AsyncMock()
    old.directory_clients["old:5222"] = old_client
    current_client = MagicMock()
    current_client.close = AsyncMock()
    current.directory_clients["new:5222"] = current_client
    bot.generations[1] = current
    bot._activate_generation(current)

    with patch("maker.bot.asyncio.sleep", new=AsyncMock()):
        await bot._retire_generation_after_grace(0, old.grace_deadline)

    assert 0 not in bot.generations
    assert bot.generations[1] is current
    old_client.close.assert_awaited_once_with()
    current_client.close.assert_not_awaited()

    dispatch = AsyncMock()
    with patch.object(bot, "_dispatch_session_handler", new=dispatch):
        await bot._handle_auth("J5Expired", "auth payload", generation_id=0)
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_old_listener_cannot_remove_current_client(bot: MakerBot) -> None:
    node_id = "directory.onion:5222"
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old_client = MagicMock()
    old_client.listen_for_messages = AsyncMock(side_effect=DirectoryClientError("lost"))
    old_client.close = AsyncMock()
    old.directory_clients[node_id] = old_client

    replacement = _generation(bot, 1)
    new_client = MagicMock()
    replacement.directory_clients[node_id] = new_client
    bot.generations[1] = replacement
    bot._activate_generation(replacement)
    bot.running = True

    with patch(
        "maker.background_tasks.spawn_task", side_effect=lambda coroutine: coroutine.close()
    ):
        await bot._listen_client(node_id, old_client, generation_id=0)

    assert bot.directory_clients[node_id] is new_client
    old_client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reconnect_result_is_discarded_after_cutover(bot: MakerBot) -> None:
    old = bot.generations[0]
    old.directory_pool.list_disconnected = MagicMock(
        return_value=[("directory.onion:5222", "directory.onion:5222")]
    )
    replacement = _generation(bot, 1)
    stale_client = MagicMock()
    stale_client.close = AsyncMock()
    bot.running = True

    async def connect(_server: str):
        bot.generations[1] = replacement
        bot._activate_generation(replacement)
        bot.running = False
        return "directory.onion:5222", stale_client

    with (
        patch("maker.background_tasks.asyncio.sleep", new=AsyncMock()),
        patch.object(bot, "_connect_to_directory", side_effect=connect),
    ):
        await bot._periodic_directory_reconnect()

    assert replacement.directory_clients == {}
    stale_client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_closes_every_generation(bot: MakerBot) -> None:
    old = bot.generations[0]
    old.state = GenerationState.GRACE
    old_client = MagicMock()
    old_client.close = AsyncMock()
    old.directory_clients["old:5222"] = old_client
    replacement = _generation(bot, 1)
    new_client = MagicMock()
    new_client.close = AsyncMock()
    replacement.directory_clients["new:5222"] = new_client
    bot.generations[1] = replacement
    bot._activate_generation(replacement)

    await bot.stop()

    assert bot.generations == {}
    old_client.close.assert_awaited_once_with()
    new_client.close.assert_awaited_once_with()
