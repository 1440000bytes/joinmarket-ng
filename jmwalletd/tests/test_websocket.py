"""Tests for jmwalletd.websocket — WebSocket endpoint."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jmwalletd.app import create_app
from jmwalletd.deps import get_daemon_state, set_daemon_state
from jmwalletd.state import CoinjoinState, DaemonState
from jmwalletd.websocket import websocket_endpoint


@pytest.fixture
def ws_client(
    daemon_state_with_wallet: DaemonState,
) -> tuple[TestClient, str]:
    """TestClient + token for WebSocket tests."""
    application = create_app(data_dir=daemon_state_with_wallet.data_dir)
    set_daemon_state(daemon_state_with_wallet)
    pair = daemon_state_with_wallet.token_authority.issue("test_wallet.jmdat")
    client = TestClient(application)
    return client, pair.token


def _wait_for_ws_client(state: DaemonState, *, timeout: float = 5.0) -> None:
    """Block until the WebSocket endpoint has authenticated a client."""
    deadline = time.monotonic() + timeout
    while (
        not any(client.generation is not None for client in state._ws_clients)
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert any(client.generation is not None for client in state._ws_clients)


class TestWebSocketAuth:
    def test_valid_auth(self, ws_client: tuple[TestClient, str]) -> None:
        client, token = ws_client
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)
            # Connection should stay open; send another message as heartbeat
            ws.send_text(token)

    def test_invalid_token_closes(self, ws_client: tuple[TestClient, str]) -> None:
        client, _ = ws_client
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text("invalid_token_here")
            # Should get disconnected
            ws.receive_text()

    def test_invalid_token_cannot_receive_queued_notification(
        self, ws_client: tuple[TestClient, str]
    ) -> None:
        client, _ = ws_client
        state = get_daemon_state()

        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/v1/ws") as ws:
            state.broadcast_ws({"txid": "private", "txdetails": {}})
            ws.send_text("invalid_token_here")
            ws.receive_text()
        assert not state._ws_clients

    def test_lock_closes_registered_socket_before_auth(
        self, ws_client: tuple[TestClient, str]
    ) -> None:
        client, token = ws_client

        with client.websocket_connect("/api/v1/ws") as ws:
            response = client.get(
                "/api/v1/wallet/test_wallet.jmdat/lock",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()

    async def test_excess_preauth_connections_are_closed(self, daemon_state: DaemonState) -> None:
        for _ in range(32):
            daemon_state.register_ws_client()
        websocket = MagicMock()
        websocket.close = AsyncMock()

        with patch("jmwalletd.websocket.get_daemon_state", return_value=daemon_state):
            await websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(
            code=1013,
            reason="Too many pending authentication requests",
        )
        assert len(daemon_state._ws_clients) == 32


class TestWebSocketNotifications:
    def test_receives_coinjoin_state(self, ws_client: tuple[TestClient, str]) -> None:
        client, token = ws_client
        state = get_daemon_state()

        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)
            _wait_for_ws_client(state)
            # Broadcast a coinjoin state change
            state.activate_coinjoin_state(CoinjoinState.NOT_RUNNING)
            # Read the notification
            msg = ws.receive_text()
            data = json.loads(msg)
            assert "coinjoin_state" in data
            assert data["coinjoin_state"] == CoinjoinState.NOT_RUNNING

    def test_receives_tx_notification(self, ws_client: tuple[TestClient, str]) -> None:
        client, token = ws_client
        state = get_daemon_state()

        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)
            _wait_for_ws_client(state)
            state.broadcast_ws({"txid": "abc123", "txdetails": {"amount": 100_000}})
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["txid"] == "abc123"

    def test_notification_before_auth_is_not_delivered(
        self, ws_client: tuple[TestClient, str]
    ) -> None:
        """A pre-auth registration cannot retain wallet notifications."""
        client, token = ws_client
        state = get_daemon_state()

        with client.websocket_connect("/api/v1/ws") as ws:
            assert len(state._ws_clients) == 1
            state.broadcast_ws({"txid": "during-auth", "txdetails": {"amount": 1}})
            ws.send_text(token)
            _wait_for_ws_client(state)
            state.broadcast_ws({"txid": "after-auth", "txdetails": {"amount": 2}})

            assert json.loads(ws.receive_text())["txid"] == "after-auth"

    def test_lock_closes_authenticated_socket_and_next_session_works(
        self, ws_client: tuple[TestClient, str]
    ) -> None:
        client, token = ws_client
        state = get_daemon_state()

        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)
            _wait_for_ws_client(state)

            response = client.get(
                "/api/v1/wallet/test_wallet.jmdat/lock",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()

        state.wallet_service = object()
        state.wallet_name = "next_wallet.jmdat"
        next_token = state.token_authority.issue("next_wallet.jmdat").token
        with client.websocket_connect("/api/v1/ws") as next_ws:
            next_ws.send_text(next_token)
            _wait_for_ws_client(state)
            state.broadcast_ws({"txid": "next-session", "txdetails": {}})
            assert json.loads(next_ws.receive_text())["txid"] == "next-session"


class TestWebSocketPaths:
    """Verify the WebSocket is reachable at all expected paths."""

    def test_jmws_path_auth(self, ws_client: tuple[TestClient, str]) -> None:
        """JAM frontend connects to /jmws."""
        client, token = ws_client
        with client.websocket_connect("/jmws") as ws:
            ws.send_text(token)
            ws.send_text(token)  # heartbeat

    def test_ws_path_auth(self, ws_client: tuple[TestClient, str]) -> None:
        """Direct connections use /ws."""
        client, token = ws_client
        with client.websocket_connect("/ws") as ws:
            ws.send_text(token)
            ws.send_text(token)


class TestWebSocketHeartbeat:
    """Tests for heartbeat re-authentication."""

    def test_invalid_heartbeat_closes_connection(self, ws_client: tuple[TestClient, str]) -> None:
        """Invalid heartbeat token after successful auth closes the connection."""
        client, token = ws_client
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)  # valid auth
            ws.send_text("invalid_heartbeat_token")  # invalid heartbeat
            ws.receive_text()  # should trigger disconnect


class TestWebSocketCleanup:
    """Tests for WebSocket client registration/cleanup."""

    def test_client_unregistered_on_disconnect(self, ws_client: tuple[TestClient, str]) -> None:
        """WebSocket client queue is unregistered after disconnect."""
        client, token = ws_client
        state = get_daemon_state()

        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(token)
            _wait_for_ws_client(state)
            assert len(state._ws_clients) == 1

        # After the context manager exits, client should be unregistered
        assert len(state._ws_clients) == 0

    def test_client_unregistered_after_auth_timeout(
        self, ws_client: tuple[TestClient, str]
    ) -> None:
        client, _ = ws_client
        state = get_daemon_state()

        with (
            patch("jmwalletd.websocket._AUTH_TIMEOUT_SECONDS", 0.01),
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/api/v1/ws") as ws,
        ):
            ws.receive_text()

        assert len(state._ws_clients) == 0
