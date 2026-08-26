"""Tests for frontend assets in the built Orderbook Watcher wheel."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

PROJECT_DIR = Path(__file__).parents[1]
EXPECTED_ASSETS = {
    "orderbook_watcher/static/index.html",
    "orderbook_watcher/static/app.js",
    "orderbook_watcher/static/style.css",
    "orderbook_watcher/static/favicon.ico",
}


def test_built_wheel_contains_frontend_assets(tmp_path: Path) -> None:
    project_copy = tmp_path / "project"
    project_copy.mkdir()
    shutil.copy2(PROJECT_DIR / "pyproject.toml", project_copy)
    shutil.copy2(PROJECT_DIR / "README.md", project_copy)
    shutil.copytree(
        PROJECT_DIR / "src",
        project_copy / "src",
        ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"),
    )

    wheel_dir = tmp_path / "wheel"
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(project_copy),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    wheels = list(wheel_dir.glob("joinmarket_orderbook_watcher-*.whl"))
    assert len(wheels) == 1
    with ZipFile(wheels[0]) as wheel:
        assert set(wheel.namelist()) >= EXPECTED_ASSETS
