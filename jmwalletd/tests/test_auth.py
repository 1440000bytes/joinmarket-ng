"""Tests for jmwalletd.auth — JWT token authority."""

from __future__ import annotations

import base64
import time

import jwt
import pytest

from jmwalletd.auth import JMTokenAuthority


class TestJMTokenAuthority:
    """Tests for JMTokenAuthority."""

    def test_initial_state(self, token_authority: JMTokenAuthority) -> None:
        assert token_authority._wallet_name == ""
        assert len(token_authority._access_key) == 64  # hex of 32 bytes
        assert len(token_authority._refresh_key) == 64

    def test_scope_empty_when_no_wallet(self, token_authority: JMTokenAuthority) -> None:
        # With empty wallet name, scope is just "walletrpc" (base64 of "")
        assert token_authority.scope.startswith("walletrpc")

    def test_scope_format(self, token_authority: JMTokenAuthority) -> None:
        token_authority._wallet_name = "test.jmdat"
        expected = "walletrpc " + base64.b64encode(b"test.jmdat").decode()
        assert token_authority.scope == expected

    def test_issue_returns_token_pair(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("my_wallet.jmdat")
        assert pair.token
        assert pair.refresh_token
        assert pair.token_type == "bearer"
        assert pair.expires_in == 1800
        assert "walletrpc" in pair.scope

    def test_issue_sets_wallet_name(self, token_authority: JMTokenAuthority) -> None:
        token_authority.issue("my_wallet.jmdat")
        assert token_authority._wallet_name == "my_wallet.jmdat"

    def test_issue_rotates_refresh_key(self, token_authority: JMTokenAuthority) -> None:
        old_refresh_key = token_authority._refresh_key
        token_authority.issue("w.jmdat")
        assert token_authority._refresh_key != old_refresh_key

    def test_issue_preserves_access_key(self, token_authority: JMTokenAuthority) -> None:
        old_access_key = token_authority._access_key
        token_authority.issue("w.jmdat")
        assert token_authority._access_key == old_access_key

    def test_verify_access_valid(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        payload = token_authority.verify_access(pair.token)
        assert "scope" in payload
        assert "exp" in payload

    def test_verify_access_wrong_key_raises(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        # Reset keys to invalidate the token
        token_authority.reset()
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_access(pair.token)

    def test_verify_access_expired_raises(self, token_authority: JMTokenAuthority) -> None:
        # Issue a token with a past expiry
        token_authority._wallet_name = "w.jmdat"
        scope = token_authority.scope
        expired_token = jwt.encode(
            {"exp": int(time.time()) - 100, "scope": scope},
            token_authority._access_key,
            algorithm="HS256",
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            token_authority.verify_access(expired_token)

    def test_verify_access_skip_exp_check(self, token_authority: JMTokenAuthority) -> None:
        token_authority._wallet_name = "w.jmdat"
        scope = token_authority.scope
        expired_token = jwt.encode(
            {"exp": int(time.time()) - 100, "scope": scope},
            token_authority._access_key,
            algorithm="HS256",
        )
        # Should succeed with verify_exp=False
        payload = token_authority.verify_access(expired_token, verify_exp=False)
        assert payload["scope"] == scope

    def test_verify_refresh_valid(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        payload = token_authority.verify_refresh(pair.refresh_token)
        assert "scope" in payload

    def test_verify_refresh_wrong_key_raises(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        # Issue again rotates refresh key, invalidating the old refresh token
        token_authority.issue("w.jmdat")
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_refresh(pair.refresh_token)

    def test_verify_access_token_as_refresh_fails(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        # Access token signed with access key should fail refresh verification
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_refresh(pair.token)

    def test_reset_clears_wallet_and_regenerates_keys(
        self, token_authority: JMTokenAuthority
    ) -> None:
        token_authority.issue("w.jmdat")
        old_access = token_authority._access_key
        old_refresh = token_authority._refresh_key
        token_authority.reset()
        assert token_authority._wallet_name == ""
        assert token_authority._access_key != old_access
        assert token_authority._refresh_key != old_refresh

    def test_reset_invalidates_all_tokens(self, token_authority: JMTokenAuthority) -> None:
        pair = token_authority.issue("w.jmdat")
        token_authority.reset()
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_access(pair.token)
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_refresh(pair.refresh_token)

    def test_multiple_issues_same_wallet(self, token_authority: JMTokenAuthority) -> None:
        pair1 = token_authority.issue("w.jmdat")
        pair2 = token_authority.issue("w.jmdat")
        # Both access tokens should still be valid (same access key)
        token_authority.verify_access(pair1.token)
        token_authority.verify_access(pair2.token)
        # Only the latest refresh token is valid
        token_authority.verify_refresh(pair2.refresh_token)
        with pytest.raises(jwt.InvalidTokenError):
            token_authority.verify_refresh(pair1.refresh_token)
