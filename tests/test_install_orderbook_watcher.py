"""Hermetic installer profile tests for the orderbook watcher package."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
COMMIT = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


def _run_packages(
    *,
    mode: str,
    selected: bool,
    installed: bool = False,
    pinned_deps: bool = False,
    unavailable_lock: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an installer package path with all external operations stubbed."""

    script = f'''\
source "{INSTALL_SH}"
set +e

print_header() {{ :; }}
print_info() {{ echo "INFO: $1"; }}
print_success() {{ echo "OK: $1"; }}
print_warning() {{ echo "WARN: $1"; }}
print_error() {{ echo "ERR: $1"; }}
get_latest_version() {{ echo "v9.9.9"; }}
resolve_to_commit_hash() {{ echo "{COMMIT}"; }}
verify_release_signature() {{ return 0; }}
verify_update_imports() {{ return 0; }}
python3() {{ return 0; }}

RELEASE_FILE_LOG="$(mktemp)"
prepare_verified_source() {{ return 0; }}
read_release_file() {{
    printf '%s\n' "$1" >> "$RELEASE_FILE_LOG"
    if [[ -n "{unavailable_lock or ""}" \
        && "$1" == "{unavailable_lock or ""}"/requirements.txt ]]; then
        return 22
    fi
    printf 'idna==3.10\n'
}}

pip() {{
    if [[ "$1" == "show" ]]; then
        [[ "$2" == "joinmarket-orderbook-watcher" && "{"true" if installed else "false"}" == "true" ]]
        return
    fi
    echo "PIP: $*"
}}

INSTALL_VERSION="v9.9.9"
INSTALL_MAKER=false
INSTALL_TAKER=false
INSTALL_TUMBLER=false
INSTALL_ORDERBOOK_WATCHER="{"true" if selected else "false"}"
SKIP_VERIFY="{"false" if pinned_deps else "true"}"
PINNED_DEPS=true

( {mode}_packages )
echo "EXIT:$?"
echo "RELEASE_FILE_LOG_START"
cat "$RELEASE_FILE_LOG"
rm -f "$RELEASE_FILE_LOG"
'''
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _pip_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [
        line.removeprefix("PIP: ")
        for line in result.stdout.splitlines()
        if line.startswith("PIP: ")
    ]


def _release_file_paths(result: subprocess.CompletedProcess[str]) -> list[str]:
    return result.stdout.split("RELEASE_FILE_LOG_START\n", maxsplit=1)[1].splitlines()


def test_orderbook_watcher_profile_selects_only_watcher() -> None:
    script = f'''\
source "{INSTALL_SH}"
parse_args --orderbook-watcher
printf '%s %s %s\n' "$INSTALL_MAKER" "$INSTALL_TAKER" "$INSTALL_ORDERBOOK_WATCHER"
'''
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "false false true"


def test_default_profile_includes_orderbook_watcher() -> None:
    script = f'''\
source "{INSTALL_SH}"
parse_args
printf '%s %s %s\n' "$INSTALL_MAKER" "$INSTALL_TAKER" "$INSTALL_ORDERBOOK_WATCHER"
'''
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "true true true"


def test_orderbook_watcher_profile_skips_interactive_role_selection() -> None:
    script = f'''\
source "{INSTALL_SH}"
parse_args --orderbook-watcher
AUTO_YES=false
read() {{ echo "unexpected prompt"; return 1; }}
ask_components
printf '%s %s %s\n' "$INSTALL_MAKER" "$INSTALL_TAKER" "$INSTALL_ORDERBOOK_WATCHER"
'''
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "unexpected prompt" not in result.stdout
    assert result.stdout.strip() == "false false true"


def test_fresh_profile_installs_orderbook_watcher() -> None:
    result = _run_packages(mode="install", selected=True)

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert "Orderbook watcher installed" in result.stdout
    assert any("subdirectory=orderbook_watcher" in line for line in _pip_lines(result))


def test_unselected_fresh_profile_omits_orderbook_watcher() -> None:
    result = _run_packages(mode="install", selected=False)

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert not any(
        "subdirectory=orderbook_watcher" in line for line in _pip_lines(result)
    )


def test_update_installs_selected_orderbook_watcher() -> None:
    result = _run_packages(mode="update", selected=True)

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert "Installing orderbook watcher" in result.stdout
    assert any("subdirectory=orderbook_watcher" in line for line in _pip_lines(result))


def test_update_preserves_existing_orderbook_watcher() -> None:
    result = _run_packages(mode="update", selected=False, installed=True)

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert "Updating orderbook watcher" in result.stdout
    assert any(
        "--force-reinstall --no-deps" in line and "orderbook_watcher" in line
        for line in _pip_lines(result)
    )


def test_orderbook_watcher_profile_fetches_lock_for_hash_verification() -> None:
    result = _run_packages(mode="install", selected=True, pinned_deps=True)

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert _release_file_paths(result) == [
        "jmcore/requirements.txt",
        "jmwallet/requirements.txt",
        "orderbook_watcher/requirements.txt",
    ]
    assert any("--require-hashes" in line for line in _pip_lines(result))


def test_update_fetches_lock_for_existing_orderbook_watcher() -> None:
    result = _run_packages(
        mode="update", selected=False, installed=True, pinned_deps=True
    )

    assert "EXIT:0" in result.stdout, result.stdout + result.stderr
    assert _release_file_paths(result) == [
        "jmcore/requirements.txt",
        "jmwallet/requirements.txt",
        "orderbook_watcher/requirements.txt",
    ]
    assert any("--require-hashes" in line for line in _pip_lines(result))


@pytest.mark.parametrize(
    ("unavailable_lock", "expected_paths"),
    [
        ("jmcore", ["jmcore/requirements.txt"]),
        ("jmwallet", ["jmcore/requirements.txt", "jmwallet/requirements.txt"]),
        (
            "orderbook_watcher",
            [
                "jmcore/requirements.txt",
                "jmwallet/requirements.txt",
                "orderbook_watcher/requirements.txt",
            ],
        ),
    ],
)
def test_orderbook_watcher_install_fails_when_a_lock_is_unavailable(
    unavailable_lock: str,
    expected_paths: list[str],
) -> None:
    result = _run_packages(
        mode="install",
        selected=True,
        pinned_deps=True,
        unavailable_lock=unavailable_lock,
    )

    assert "EXIT:1" in result.stdout, result.stdout + result.stderr
    assert "without all dependency locks" in result.stdout
    assert _release_file_paths(result) == expected_paths
    assert not _pip_lines(result)
