"""Orderbook proxy endpoints.

Proxies JAM's ``/obwatch/`` requests to the orderbook_watcher HTTP server.
The orderbook_watcher runs independently on its own port (default 8000) and
provides the live orderbook data from directory servers.
"""

from __future__ import annotations

import aiohttp
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from loguru import logger

from jmwalletd.deps import get_daemon_state
from jmwalletd.state import DaemonState

router = APIRouter()


def _get_obwatch_url(state: DaemonState) -> str:
    """Get the orderbook watcher base URL from settings."""
    try:
        from jmcore.settings import get_settings

        settings = get_settings()
        host = settings.orderbook_watcher.http_host
        port = settings.orderbook_watcher.http_port
        return f"http://{host}:{port}"
    except Exception:
        # Default if settings aren't available.
        return "http://127.0.0.1:8000"


@router.get("/obwatch/orderbook.json")
async def get_orderbook(
    state: DaemonState = Depends(get_daemon_state),
) -> JSONResponse:
    """Proxy orderbook data from the orderbook_watcher service."""
    url = f"{_get_obwatch_url(state)}/orderbook.json"
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            if resp.status == 200:
                data = await resp.json()
                return JSONResponse(content=data)
            logger.warning("Orderbook watcher returned status {}", resp.status)
            return JSONResponse(
                content={"offers": [], "fidelitybonds": []},
                status_code=502,
            )
    except Exception:
        logger.warning("Could not reach orderbook watcher at {}", url)
        return JSONResponse(
            content={"offers": [], "fidelitybonds": []},
            status_code=502,
        )


@router.get("/obwatch/refreshorderbook")
async def refresh_orderbook(
    state: DaemonState = Depends(get_daemon_state),
) -> JSONResponse:
    """Request the orderbook watcher to refresh its cache.

    The reference implementation reloads the orderbook on this endpoint.
    Our orderbook_watcher auto-refreshes every 30s, so this is a no-op
    proxy that just returns the latest data.
    """
    url = f"{_get_obwatch_url(state)}/orderbook.json"
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            if resp.status == 200:
                data = await resp.json()
                return JSONResponse(content=data)
            return JSONResponse(content={"offers": [], "fidelitybonds": []})
    except Exception:
        return JSONResponse(content={"offers": [], "fidelitybonds": []})
