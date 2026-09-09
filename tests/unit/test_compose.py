from pathlib import Path
from typing import Any, cast

import yaml


def test_only_gateway_has_host_edge_access() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = cast(dict[str, Any], yaml.safe_load((root / "docker-compose.yml").read_text()))
    networks = cast(dict[str, dict[str, Any] | None], compose["networks"])
    services = cast(dict[str, dict[str, Any]], compose["services"])

    assert networks["application"] == {"internal": True}
    assert networks["edge"] is None
    assert services["gateway"]["networks"] == ["application", "edge"]
    assert services["grafana"]["networks"] == ["application", "edge"]
    assert services["gateway"]["ports"] == ["127.0.0.1:${INCIDENTPILOT_GATEWAY_PORT:-8000}:8000"]
    assert services["grafana"]["ports"] == ["127.0.0.1:3000:3000"]
    for name in {
        "auth",
        "data",
        "worker",
        "migrate",
        "postgres",
        "redis",
        "prometheus",
        "loki",
        "tempo",
        "otel-collector",
    }:
        assert "edge" not in services[name].get("networks", [])
        assert "ports" not in services[name]


def test_observability_containers_are_unprivileged_without_docker_socket() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = cast(dict[str, Any], yaml.safe_load((root / "docker-compose.yml").read_text()))
    services = cast(dict[str, dict[str, Any]], compose["services"])
    for name in {"prometheus", "loki", "tempo", "otel-collector", "grafana"}:
        service = services[name]
        assert not service.get("privileged", False)
        assert "/var/run/docker.sock" not in str(service.get("volumes", []))
        assert "ALL" in service.get("cap_drop", [])
