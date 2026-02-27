"""FastAPI application factory.

Creates the ``FastAPI`` app with:
- CORS middleware matching reference implementation (``Access-Control-Allow-Origin: *``).
- All API routes under ``/api/v1``.
- WebSocket endpoint at ``/ws`` (for direct connections) and ``/api/v1/ws``.
- Global exception handlers that produce reference-compatible error responses.
- Cache-busting response headers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from jmwalletd.deps import set_daemon_state
from jmwalletd.errors import JMWalletDaemonError
from jmwalletd.state import DaemonState


def create_app(*, data_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        data_dir: JoinMarket data directory. Defaults to ``~/.joinmarket-ng``.

    Returns:
        Configured FastAPI app ready to serve.
    """
    app = FastAPI(
        title="JoinMarket wallet daemon",
        description="JAM-compatible HTTP/WebSocket API for JoinMarket-NG",
        version="0.17.0",
        docs_url=None,  # Disable Swagger UI in production.
        redoc_url=None,
    )

    # ------------------------------------------------------------------
    # CORS -- match reference implementation's permissive policy.
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # ------------------------------------------------------------------
    # Daemon state singleton.
    # ------------------------------------------------------------------
    state = DaemonState(data_dir=data_dir)
    set_daemon_state(state)

    # ------------------------------------------------------------------
    # Cache-busting response headers (matching reference).
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def add_cache_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "Sat, 26 Jul 1997 05:00:00 GMT"
        return response

    # ------------------------------------------------------------------
    # Exception handlers.
    # ------------------------------------------------------------------
    @app.exception_handler(JMWalletDaemonError)
    async def daemon_error_handler(request: Request, exc: JMWalletDaemonError) -> JSONResponse:
        headers: dict[str, str] = {}

        # Add WWW-Authenticate header for 401/403 errors (per RFC 6750).
        if exc.status_code in (401, 403):
            error_type = "invalid_token" if exc.status_code == 401 else "insufficient_scope"
            headers["WWW-Authenticate"] = (
                f'Bearer, error="{error_type}", error_description="{exc.detail}"'
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Register routers.
    # ------------------------------------------------------------------
    from jmwalletd.routers.coinjoin import router as coinjoin_router
    from jmwalletd.routers.obwatch import router as obwatch_router
    from jmwalletd.routers.wallet import router as wallet_router
    from jmwalletd.routers.wallet_data import router as wallet_data_router
    from jmwalletd.websocket import router as ws_router

    app.include_router(wallet_router, prefix="/api/v1")
    app.include_router(wallet_data_router, prefix="/api/v1")
    app.include_router(coinjoin_router, prefix="/api/v1")
    app.include_router(obwatch_router, prefix="/api/v1")

    # JAM also calls /obwatch/* without the /api/v1 prefix.
    app.include_router(obwatch_router)

    # WebSocket: available at /ws (direct), /api/v1/ws (prefixed),
    # and /jmws (what JAM frontend connects to).
    app.include_router(ws_router, prefix="/ws")
    app.include_router(ws_router, prefix="/jmws")
    app.include_router(ws_router, prefix="/api/v1/ws")

    # ------------------------------------------------------------------
    # Serve JAM static files (if present).
    # ------------------------------------------------------------------
    # Look in data_dir/jam or system path /usr/share/jmwalletd/jam
    jam_dirs = [
        state.data_dir / "jam",
        Path("/usr/share/jmwalletd/jam"),
    ]
    static_dir: Path | None = None
    for d in jam_dirs:
        if d.exists() and (d / "index.html").exists():
            static_dir = d
            break

    if static_dir:
        logger.info("Serving JAM from {}", static_dir)
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        # Serve /assets folder
        if (static_dir / "assets").exists():
            app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        # SPA catch-all handler
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> Any:
            # If the path exists as a file, serve it (e.g. favicon.ico, manifest.json)
            # excluding index.html to avoid serving it directly (optional)
            path_obj = static_dir / full_path
            if full_path != "" and path_obj.exists() and path_obj.is_file():
                return FileResponse(path_obj)

            # Otherwise serve index.html for client-side routing
            return FileResponse(static_dir / "index.html")

    # ------------------------------------------------------------------
    # CORS preflight handler for root (matching reference).
    # ------------------------------------------------------------------
    @app.options("/")
    async def cors_preflight() -> JSONResponse:
        return JSONResponse(
            content={},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST",
            },
        )

    logger.info("jmwalletd app created (data_dir={})", state.data_dir)
    return app
