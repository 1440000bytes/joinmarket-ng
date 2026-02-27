"""End-to-end tests for jmwalletd API daemon.

These tests exercise the jmwalletd HTTP API against a real running container
backed by a Bitcoin Core regtest node, validating the full wallet lifecycle
and data endpoints that JAM relies on.

Requires: ``docker compose --profile e2e up -d``
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest

pytestmark = pytest.mark.e2e

JMWALLETD_URL = "http://127.0.0.1:28183"
API = f"{JMWALLETD_URL}/api/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wallet_name() -> str:
    """Return a unique wallet filename for test isolation."""
    return f"test-{uuid.uuid4().hex[:8]}.jmdat"


async def _wait_for_jmwalletd(timeout: float = 60.0) -> None:
    """Block until jmwalletd is responding on its HTTP port."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{API}/getinfo", timeout=5)
                if r.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(1.0)
    pytest.fail(f"jmwalletd did not become ready within {timeout}s")


async def _create_wallet(
    client: httpx.AsyncClient,
    name: str | None = None,
    password: str = "testpass",
) -> tuple[str, str, str]:
    """Create a wallet and return (walletname, access_token, refresh_token)."""
    name = name or _wallet_name()
    r = await client.post(
        f"{API}/wallet/create",
        json={
            "walletname": name,
            "password": password,
            "wallettype": "sw-fb",
        },
    )
    assert r.status_code == 201, f"wallet/create failed: {r.status_code} {r.text}"
    body = r.json()
    return name, body["token"], body["refresh_token"]


async def _unlock_wallet(
    client: httpx.AsyncClient,
    name: str,
    password: str = "testpass",
) -> tuple[str, str]:
    """Unlock a wallet and return (access_token, refresh_token)."""
    r = await client.post(
        f"{API}/wallet/{name}/unlock",
        json={"password": password},
    )
    assert r.status_code == 200, f"wallet/unlock failed: {r.status_code} {r.text}"
    body = r.json()
    return body["token"], body["refresh_token"]


def _auth(token: str) -> dict[str, str]:
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def jmwalletd_ready() -> None:
    """Ensure jmwalletd is reachable before running any tests in this module."""
    await _wait_for_jmwalletd()


@pytest.fixture()
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Shared async HTTP client."""
    async with httpx.AsyncClient(timeout=30) as c:
        yield c


@pytest.fixture()
async def wallet(
    client: httpx.AsyncClient,
    jmwalletd_ready: None,
) -> AsyncGenerator[tuple[str, str, str], None]:
    """Create a fresh wallet and lock it after the test.

    Returns (walletname, token, refresh_token).
    """
    name, token, refresh = await _create_wallet(client)
    yield name, token, refresh
    # Cleanup: lock wallet so the next test starts clean
    try:
        await client.get(f"{API}/wallet/{name}/lock", headers=_auth(token))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests — Server Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_getinfo(client: httpx.AsyncClient, jmwalletd_ready: None) -> None:
    """GET /api/v1/getinfo returns 200 with a version string."""
    r = await client.get(f"{API}/getinfo")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body


@pytest.mark.asyncio
async def test_session_no_wallet(
    client: httpx.AsyncClient,
    jmwalletd_ready: None,
) -> None:
    """GET /api/v1/session with no wallet loaded."""
    r = await client.get(f"{API}/session")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_loaded"] is False


# ---------------------------------------------------------------------------
# Tests — Wallet Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_wallet(
    client: httpx.AsyncClient,
    jmwalletd_ready: None,
) -> None:
    """POST /api/v1/wallet/create returns 201 with tokens and seedphrase."""
    name = _wallet_name()
    r = await client.post(
        f"{API}/wallet/create",
        json={"walletname": name, "password": "pw123", "wallettype": "sw-fb"},
    )
    assert r.status_code == 201
    body = r.json()
    assert "token" in body
    assert "refresh_token" in body
    assert "seedphrase" in body
    assert len(body["seedphrase"].split()) == 12

    # Lock to clean up
    await client.get(f"{API}/wallet/{name}/lock", headers=_auth(body["token"]))


@pytest.mark.asyncio
async def test_unlock_and_lock_wallet(
    client: httpx.AsyncClient,
    jmwalletd_ready: None,
) -> None:
    """Create, lock, then re-unlock a wallet."""
    name = _wallet_name()
    _, token, _ = await _create_wallet(client, name)
    await client.get(f"{API}/wallet/{name}/lock", headers=_auth(token))

    token, _ = await _unlock_wallet(client, name)

    # Session should show wallet loaded
    r = await client.get(f"{API}/session", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["wallet_loaded"] is True

    await client.get(f"{API}/wallet/{name}/lock", headers=_auth(token))


@pytest.mark.asyncio
async def test_list_wallets(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/wallet/all includes our wallet."""
    name, _, _ = wallet
    r = await client.get(f"{API}/wallet/all")
    assert r.status_code == 200
    assert name in r.json()["wallets"]


@pytest.mark.asyncio
async def test_token_refresh(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """POST /api/v1/token with refresh_token returns new token pair."""
    _, token, refresh = wallet
    r = await client.post(
        f"{API}/token",
        json={"grant_type": "refresh_token", "refresh_token": refresh},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert "refresh_token" in body


# ---------------------------------------------------------------------------
# Tests — Wallet Data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wallet_display(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/wallet/{name}/display returns wallet structure."""
    name, token, _ = wallet
    r = await client.get(f"{API}/wallet/{name}/display", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "walletinfo" in body


@pytest.mark.asyncio
async def test_wallet_utxos(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/wallet/{name}/utxos returns (possibly empty) UTXO list."""
    name, token, _ = wallet
    r = await client.get(f"{API}/wallet/{name}/utxos", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "utxos" in body
    assert isinstance(body["utxos"], list)


@pytest.mark.asyncio
async def test_new_address(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/wallet/{name}/address/new/0 returns a bcrt1 address."""
    name, token, _ = wallet
    r = await client.get(
        f"{API}/wallet/{name}/address/new/0",
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert "address" in body
    # Regtest bech32 addresses start with bcrt1
    assert body["address"].startswith("bcrt1")


@pytest.mark.asyncio
async def test_get_seed(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/wallet/{name}/getseed returns 12-word mnemonic."""
    name, token, _ = wallet
    r = await client.get(f"{API}/wallet/{name}/getseed", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "seedphrase" in body
    assert len(body["seedphrase"].split()) == 12


# ---------------------------------------------------------------------------
# Tests — Auth Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_required_without_token(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """Authenticated endpoints reject requests without a token."""
    name, _, _ = wallet
    r = await client.get(f"{API}/wallet/{name}/display")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_required_bad_token(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """Authenticated endpoints reject requests with an invalid token."""
    name, _, _ = wallet
    r = await client.get(
        f"{API}/wallet/{name}/display",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Tests — Session with Wallet Loaded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_with_wallet(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """GET /api/v1/session with auth returns full session info."""
    name, token, _ = wallet
    r = await client.get(f"{API}/session", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_loaded"] is True
    assert body["wallet_name"] == name
    assert body["maker_running"] is False
    assert body["taker_running"] is False


# ---------------------------------------------------------------------------
# Tests — Error Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_duplicate_wallet(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """Cannot create a wallet while another is already loaded."""
    r = await client.post(
        f"{API}/wallet/create",
        json={"walletname": _wallet_name(), "password": "pw", "wallettype": "sw-fb"},
    )
    # Should reject because a wallet is already loaded
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_unlock_nonexistent_wallet(
    client: httpx.AsyncClient,
    jmwalletd_ready: None,
) -> None:
    """Unlocking a wallet that doesn't exist returns an error."""
    r = await client.post(
        f"{API}/wallet/no-such-wallet.jmdat/unlock",
        json={"password": "pw"},
    )
    assert r.status_code in (404, 500)


@pytest.mark.asyncio
async def test_lock_wrong_wallet_name(
    client: httpx.AsyncClient,
    wallet: tuple[str, str, str],
) -> None:
    """Locking a wallet name that doesn't match the loaded one fails."""
    _, token, _ = wallet
    r = await client.get(
        f"{API}/wallet/wrong-name.jmdat/lock",
        headers=_auth(token),
    )
    # Should fail — wallet name mismatch
    assert r.status_code in (400, 409)
