"""JWT token authority for the wallet daemon.

Implements HS256-based JWT tokens compatible with the reference JoinMarket
implementation.  Two token types are managed:

- **Access token**: short-lived (30 min), used in Authorization / x-jm-authorization headers.
- **Refresh token**: longer-lived (4 hr), used only to obtain new token pairs.

Signing keys are regenerated on daemon start and on each wallet unlock/create/lock cycle,
ensuring tokens from previous sessions are always invalidated.
"""

from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass, field

import jwt

ACCESS_TOKEN_EXPIRY_SECONDS = 1800  # 30 minutes
REFRESH_TOKEN_EXPIRY_SECONDS = 14400  # 4 hours
LEEWAY_SECONDS = 10


@dataclass
class TokenPair:
    """A pair of access + refresh tokens with metadata."""

    token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRY_SECONDS
    scope: str = ""


@dataclass
class JMTokenAuthority:
    """Manages JWT signing keys and token issuance/verification.

    Compatible with the reference implementation's auth semantics:
    - Access and refresh tokens use separate signing keys.
    - Refresh key is rotated on every token refresh.
    - All keys are regenerated on reset (wallet lock/unlock cycle).
    """

    _access_key: str = field(default_factory=lambda: secrets.token_hex(32))
    _refresh_key: str = field(default_factory=lambda: secrets.token_hex(32))
    _wallet_name: str = ""

    @property
    def scope(self) -> str:
        """Return the current scope string for token payloads."""
        if not self._wallet_name:
            return "walletrpc"
        b64_name = base64.b64encode(self._wallet_name.encode()).decode()
        return f"walletrpc {b64_name}"

    def reset(self) -> None:
        """Regenerate all signing keys, invalidating all existing tokens."""
        self._access_key = secrets.token_hex(32)
        self._refresh_key = secrets.token_hex(32)
        self._wallet_name = ""

    def issue(self, wallet_name: str) -> TokenPair:
        """Issue a new access + refresh token pair for the given wallet.

        The refresh signing key is rotated on each call, invalidating any
        previously issued refresh token.
        """
        self._wallet_name = wallet_name
        self._refresh_key = secrets.token_hex(32)

        now = time.time()
        scope = self.scope

        access_payload = {"exp": now + ACCESS_TOKEN_EXPIRY_SECONDS, "scope": scope}
        refresh_payload = {"exp": now + REFRESH_TOKEN_EXPIRY_SECONDS, "scope": scope}

        access_token = jwt.encode(access_payload, self._access_key, algorithm="HS256")
        refresh_token = jwt.encode(refresh_payload, self._refresh_key, algorithm="HS256")

        return TokenPair(
            token=access_token,
            refresh_token=refresh_token,
            scope=scope,
        )

    def verify_access(self, token: str, *, verify_exp: bool = True) -> dict[str, str]:
        """Verify an access token and return the decoded payload.

        Args:
            token: The raw JWT string.
            verify_exp: Whether to enforce expiration. Set to False for the
                token-refresh flow (the expired access token is still accepted).

        Raises:
            jwt.InvalidTokenError: On any verification failure.
        """
        options = {}
        if not verify_exp:
            options["verify_exp"] = False

        payload: dict[str, str] = jwt.decode(
            token,
            self._access_key,
            algorithms=["HS256"],
            leeway=LEEWAY_SECONDS,
            options=options,  # type: ignore[arg-type]
        )

        # Validate scope includes our expected scope.
        token_scope = payload.get("scope", "")
        if not self.scope:
            return payload
        if self.scope not in token_scope:
            msg = f"Scope mismatch: expected '{self.scope}' in '{token_scope}'"
            raise jwt.InvalidTokenError(msg)

        return payload

    def verify_refresh(self, token: str) -> dict[str, str]:
        """Verify a refresh token and return the decoded payload.

        Raises:
            jwt.InvalidTokenError: On any verification failure.
        """
        payload: dict[str, str] = jwt.decode(
            token,
            self._refresh_key,
            algorithms=["HS256"],
            leeway=LEEWAY_SECONDS,
        )

        token_scope = payload.get("scope", "")
        if self.scope and self.scope not in token_scope:
            msg = f"Scope mismatch: expected '{self.scope}' in '{token_scope}'"
            raise jwt.InvalidTokenError(msg)

        return payload
