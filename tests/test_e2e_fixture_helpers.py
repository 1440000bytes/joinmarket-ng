from __future__ import annotations

from tests.e2e import conftest, docker_utils


def test_neutrino_readiness_ignores_unrelated_host_service(monkeypatch) -> None:
    monkeypatch.setattr(
        docker_utils,
        "get_container_name",
        lambda service: f"suite-{service}",
    )
    monkeypatch.setattr(
        docker_utils,
        "docker_inspect_running",
        lambda container: False,
    )

    def unexpected_port_probe(*_args, **_kwargs) -> bool:
        raise AssertionError("Host port must not be probed without a suite container")

    monkeypatch.setattr(conftest, "is_port_open", unexpected_port_probe)

    assert conftest.wait_for_neutrino_ready_if_present(timeout=0.01)
