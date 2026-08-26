"""WebSocket endpoint for push notifications.

Implements the reference JoinMarket WebSocket protocol:
1. Client connects.
2. Client sends its JWT access token as a plain text message.
3. Server verifies the token.
4. On success, the client starts receiving JSON notifications.
5. Any non-token message or invalid token drops the connection.

Notification types:
- ``{"coinjoin_state": <int>}`` -- coinjoin state change.
- ``{"txid": "...", "txdetails": {...}}`` -- a wallet transaction. Emitted for
  every transaction that affects the wallet (external deposits, maker/taker
  coinjoins, and sends), once when first seen in the mempool and again when it
  first confirms (``txdetails.confirmations`` carries the count). Clients should
  treat it as a signal to reload balances/UTXOs.
"""

from __future__ import annotations

import asyncio
import contextlib

import jwt as pyjwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from jmwalletd.deps import get_daemon_state
from jmwalletd.state import WebSocketControl, WebSocketNotification

router = APIRouter()

# Mounted at /ws, /jmws, and /api/v1/ws in app.py.
_WS_PATH = ""


@router.websocket(_WS_PATH)
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle a WebSocket connection with token-based authentication."""
    state = get_daemon_state()
    # Register before accepting so lock can terminate a socket while it waits
    # for authentication. The client receives no notifications until the token
    # is verified and it is bound to the current wallet generation.
    client = state.register_ws_client()

    try:
        await websocket.accept()

        # Wait for the auth token (first message), but also observe a lock
        # while this socket is registered but not yet authenticated.
        auth_task = asyncio.create_task(websocket.receive_text())
        control_task = asyncio.create_task(client.queue.get())
        done, pending = await asyncio.wait(
            [auth_task, control_task], timeout=30.0, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            for task in pending:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*pending)
            raise TimeoutError
        if control_task in done:
            auth_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await auth_task
            await websocket.close(code=4001, reason="Wallet session ended")
            return

        control_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await control_task
        token_msg = auth_task.result()

        # Verify the token.
        try:
            state.token_authority.verify_access(token_msg.strip())
        except pyjwt.InvalidTokenError as exc:
            logger.debug("WebSocket auth failed: {}", exc)
            await websocket.close(code=4001, reason="Invalid token")
            return
        if not state.authenticate_ws_client(client):
            await websocket.close(code=4001, reason="Wallet session ended")
            return

        # Run two tasks concurrently:
        # 1. Read incoming messages (heartbeat tokens or close).
        # 2. Send outgoing notifications from the queue.
        async def _reader() -> None:
            """Read incoming messages. Heartbeat tokens are re-verified."""
            while True:
                try:
                    msg = await websocket.receive_text()
                    # Treat any incoming message as a heartbeat token re-auth.
                    try:
                        state.token_authority.verify_access(msg.strip())
                    except pyjwt.InvalidTokenError:
                        logger.debug("WebSocket heartbeat token invalid, dropping")
                        await websocket.close(code=4001, reason="Invalid token")
                        return
                except WebSocketDisconnect:
                    return

        async def _writer() -> None:
            """Send queued notifications to the client."""
            while True:
                event = await client.queue.get()
                if event is WebSocketControl.CLOSE:
                    await websocket.close(code=4001, reason="Wallet session ended")
                    return
                assert isinstance(event, WebSocketNotification)
                if not state.ws_client_is_current(client, event.generation):
                    await websocket.close(code=4001, reason="Wallet session ended")
                    return
                try:
                    await websocket.send_text(event.text)
                except Exception:
                    return

        # Run reader and writer concurrently; when either exits, we're done.
        reader_task = asyncio.create_task(_reader())
        writer_task = asyncio.create_task(_writer())

        done, pending = await asyncio.wait(
            [reader_task, writer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

    except TimeoutError:
        logger.debug("WebSocket auth timeout")
        await websocket.close(code=4002, reason="Auth timeout")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.error("WebSocket error")
        logger.bind(sensitive=True).exception("WebSocket error")
    finally:
        state.unregister_ws_client(client)
