from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
IMAGES = {
    "directory-server",
    "directory-server-debug",
    "orderbook-watcher",
    "maker",
    "taker",
    "jmwalletd",
}
PLATFORMS = {"linux/amd64", "linux/arm64", "linux/arm/v7"}
PRODUCTION_LOCKS = {
    "directory_server/requirements.txt",
    "jmcore/requirements.txt",
    "jmwallet/requirements.txt",
    "jmwalletd/requirements.txt",
    "maker/requirements.txt",
    "orderbook_watcher/requirements.txt",
    "taker/requirements.txt",
    "tumbler/requirements.txt",
}
BITCOINTX_PACKAGES = {"jmcore", "jmwallet", "jmwalletd"}
BITCOINTX_WHEEL_SHA256 = (
    "6162a46e1eeb20230a23415e303cfdcbc266f9f0261687cdf37db68957e1b4f8"
)
RUNTIME_IMAGE_STAGES = {
    "directory_server/Dockerfile": {"production", "debug"},
    "jmwalletd/Dockerfile": {"jmwalletd"},
    "maker/Dockerfile": {"production"},
    "orderbook_watcher/Dockerfile": {"production"},
    "taker/Dockerfile": {"production"},
}


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_dependency_updates_remain_maintainer_driven() -> None:
    assert not (REPO_ROOT / ".github" / "dependabot.yml").exists()


def _dockerfile_stage(path: str, stage: str) -> str:
    lines = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.endswith(f" AS {stage}")
    )
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start + 1)
            if line.startswith("FROM ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_python_security_workflow_audits_locks_and_fresh_resolution() -> None:
    jobs = _workflow("security.yaml")["jobs"]

    lock_matrix = jobs["audit-production-locks"]["strategy"]["matrix"]
    assert set(lock_matrix["requirements"]) == PRODUCTION_LOCKS

    fresh_steps = jobs["audit-fresh-resolution"]["steps"]
    fresh_commands = "\n".join(step.get("run", "") for step in fresh_steps)
    assert '--path "$target_site_packages" --skip-editable' in fresh_commands
    assert "requirements-security.txt" in fresh_commands


def test_codeql_uses_extended_queries_for_supported_sources() -> None:
    jobs = _workflow("codeql.yaml")["jobs"]
    analyze = jobs["analyze"]

    assert set(analyze["strategy"]["matrix"]["language"]) == {
        "python",
        "javascript-typescript",
        "actions",
    }
    init = next(
        step for step in analyze["steps"] if step["name"] == "Initialize CodeQL"
    )
    assert init["with"]["queries"] == "+security-extended"


def test_image_scanner_covers_published_images_and_defaults_to_all_platforms() -> None:
    workflow = _workflow("image-security.yaml")
    matrix = workflow["jobs"]["scan"]["strategy"]["matrix"]
    workflow_text = (WORKFLOWS / "image-security.yaml").read_text(encoding="utf-8")

    assert set(matrix["image"]) == IMAGES
    assert all(platform in workflow_text for platform in PLATFORMS)
    assert '\'["main", "latest"]\'' in workflow_text
    assert "severity: HIGH,CRITICAL" in workflow_text
    assert "ignore-unfixed: true" in workflow_text
    assert "exit-code: '1'" in workflow_text


def test_runtime_images_exclude_python_package_installers() -> None:
    for dockerfile, stages in RUNTIME_IMAGE_STAGES.items():
        for stage in stages:
            stage_text = _dockerfile_stage(dockerfile, stage)
            assert "/usr/local/bin/pip*" in stage_text
            assert "/ensurepip" in stage_text
            assert "/site-packages/pip" in stage_text
            assert "/site-packages/pip-*.dist-info" in stage_text

    jmwalletd_builder = _dockerfile_stage("jmwalletd/Dockerfile", "builder")
    assert "/opt/venv/bin/pip*" in jmwalletd_builder
    assert (
        "/opt/venv/lib/python${PYTHON_VERSION%.*}/site-packages/pip"
        in jmwalletd_builder
    )


def test_runtime_images_include_native_secp256k1() -> None:
    for dockerfile, stages in RUNTIME_IMAGE_STAGES.items():
        for stage in stages:
            assert "libsecp256k1-2=0.5.0-2+b1" in _dockerfile_stage(dockerfile, stage)


def test_bitcointx_dependency_is_pinned_to_release_wheel() -> None:
    expected_url = (
        "https://github.com/m0wer/python-bitcointx/releases/download/python-bitcointx-v2.1.0/"
        "python_bitcointx-2.1.0-py3-none-any.whl"
    )
    for package in BITCOINTX_PACKAGES:
        manifest = (REPO_ROOT / package / "pyproject.toml").read_text(encoding="utf-8")
        assert "coincurve" not in manifest
        assert expected_url in manifest
        assert BITCOINTX_WHEEL_SHA256 in manifest

        for lock_name in ("requirements.txt", "requirements-dev.txt"):
            lock = (REPO_ROOT / package / lock_name).read_text(encoding="utf-8")
            assert "coincurve" not in lock
            assert expected_url in lock
            assert BITCOINTX_WHEEL_SHA256 in lock


def test_main_and_release_promotions_depend_on_image_scans() -> None:
    ci_jobs = _workflow("ci.yaml")["jobs"]
    release_jobs = _workflow("release.yaml")["jobs"]

    assert {"scan-amd64", "scan-arm64", "scan-armv7"}.issubset(
        set(ci_jobs["publish-images"]["needs"])
    )
    assert release_jobs["scan-candidate-images"]["needs"] == "build-candidate-images"
    assert set(release_jobs["promote-docker-images"]["needs"]) == {
        "prepare",
        "scan-candidate-images",
    }
    assert set(release_jobs["create-release"]["needs"]) == {
        "prepare",
        "promote-docker-images",
    }

    candidate_matrix = release_jobs["build-candidate-images"]["strategy"]["matrix"][
        "include"
    ]
    promotion_matrix = release_jobs["promote-docker-images"]["strategy"]["matrix"][
        "include"
    ]
    assert {entry["image"] for entry in candidate_matrix} == IMAGES
    assert {entry["image"] for entry in promotion_matrix} == IMAGES
