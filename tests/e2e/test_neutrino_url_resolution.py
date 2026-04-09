from __future__ import annotations

from tests.e2e.conftest import _resolve_neutrino_url


def test_resolve_neutrino_url_upgrades_http_with_auth_token() -> None:
    assert (
        _resolve_neutrino_url("http://127.0.0.1:8334", "token")
        == "https://127.0.0.1:8334"
    )


def test_resolve_neutrino_url_keeps_https_with_auth_token() -> None:
    assert (
        _resolve_neutrino_url("https://127.0.0.1:8334", "token")
        == "https://127.0.0.1:8334"
    )


def test_resolve_neutrino_url_keeps_http_without_auth_token() -> None:
    assert (
        _resolve_neutrino_url("http://127.0.0.1:8334", None) == "http://127.0.0.1:8334"
    )


def test_resolve_neutrino_url_defaults_https_when_auth_token_present() -> None:
    assert _resolve_neutrino_url(None, "token") == "https://127.0.0.1:8334"


def test_resolve_neutrino_url_defaults_http_without_auth_token() -> None:
    assert _resolve_neutrino_url(None, None) == "http://127.0.0.1:8334"
