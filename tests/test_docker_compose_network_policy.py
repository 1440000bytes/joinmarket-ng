from __future__ import annotations

from pathlib import Path

import yaml


COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
LOCAL_DIRECTORY_CLIENTS = {
    "orderbook-watcher",
    "jmwalletd",
    "jam-playwright",
    "maker",
    "migration-maker",
    "taker",
    "taker-reference",
    "maker1",
    "maker2",
    "maker3",
    "maker4",
    "maker5",
    "maker-neutrino",
    "taker-neutrino",
}


def test_local_directory_clients_explicitly_allow_development_clearnet() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text())

    for service_name in LOCAL_DIRECTORY_CLIENTS:
        environment = compose["services"][service_name]["environment"]
        assert "NETWORK_CONFIG__ALLOW_CLEARNET_CONNECTIONS=true" in environment
