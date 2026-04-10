from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_update_flatpak_deps_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "update-flatpak-deps.py"
    )
    spec = importlib.util.spec_from_file_location("update_flatpak_deps", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replace_url_sha_updates_tor_entry() -> None:
    module = _load_update_flatpak_deps_module()
    manifest_path = (
        Path(__file__).resolve().parents[1] / "flatpak" / "org.joinmarketng.JamNG.yml"
    )
    manifest_text = manifest_path.read_text(encoding="utf-8")

    current_url, current_sha = module.extract_url_sha(
        module.TOR_RE, manifest_text, "tor"
    )
    assert current_url.startswith("https://dist.torproject.org/tor-")
    assert len(current_sha) == 64

    new_url = "https://dist.torproject.org/tor-0.4.9.99.tar.gz"
    new_sha = "a" * 64
    updated_text = module.replace_url_sha(
        module.TOR_RE, manifest_text, new_url, new_sha, "tor"
    )

    assert new_url in updated_text
    assert f"sha256: {new_sha}" in updated_text


def test_replace_jam_commit_updates_commit() -> None:
    module = _load_update_flatpak_deps_module()
    manifest_path = (
        Path(__file__).resolve().parents[1] / "flatpak" / "org.joinmarketng.JamNG.yml"
    )
    manifest_text = manifest_path.read_text(encoding="utf-8")

    current_commit = module.extract_jam_commit(manifest_text)
    assert len(current_commit) == 40

    new_commit = "f" * 40
    updated_text = module.replace_jam_commit(manifest_text, new_commit)

    assert f"commit: {new_commit}" in updated_text
    assert f"commit: {current_commit}" not in updated_text


def test_latest_tor_version_selects_highest(monkeypatch) -> None:
    module = _load_update_flatpak_deps_module()
    html = """
    <a href='tor-0.4.8.23.tar.gz'>tor-0.4.8.23.tar.gz</a>
    <a href='tor-0.4.9.5.tar.gz'>tor-0.4.9.5.tar.gz</a>
    <a href='tor-0.4.9.6.tar.gz'>tor-0.4.9.6.tar.gz</a>
    """
    monkeypatch.setattr(module, "fetch_text", lambda _url: html)

    assert module.latest_tor_version() == "0.4.9.6"


def test_latest_libsodium_source_url_prefers_release_asset() -> None:
    module = _load_update_flatpak_deps_module()
    release = {
        "tag_name": "1.0.21-RELEASE",
        "assets": [
            {
                "name": "libsodium-1.0.21.tar.gz",
                "browser_download_url": "https://example.com/libsodium-1.0.21.tar.gz",
            }
        ],
        "tarball_url": "https://api.github.com/repos/jedisct1/libsodium/tarball/1.0.21-RELEASE",
    }

    assert (
        module.latest_libsodium_source_url(release)
        == "https://example.com/libsodium-1.0.21.tar.gz"
    )


def test_latest_libsodium_source_url_falls_back_to_download_site() -> None:
    module = _load_update_flatpak_deps_module()
    release = {
        "tag_name": "1.0.22-RELEASE",
        "assets": [],
        "tarball_url": "https://api.github.com/repos/jedisct1/libsodium/tarball/1.0.22-RELEASE",
    }

    assert (
        module.latest_libsodium_source_url(release)
        == "https://download.libsodium.org/libsodium/releases/libsodium-1.0.22.tar.gz"
    )


def test_latest_libsodium_source_url_falls_back_to_tarball_url() -> None:
    module = _load_update_flatpak_deps_module()
    release = {
        "tag_name": "latest",
        "assets": [],
        "tarball_url": "https://api.github.com/repos/jedisct1/libsodium/tarball/1.0.22-RELEASE",
    }

    assert (
        module.latest_libsodium_source_url(release)
        == "https://api.github.com/repos/jedisct1/libsodium/tarball/1.0.22-RELEASE"
    )
