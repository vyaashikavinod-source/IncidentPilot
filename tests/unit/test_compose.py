from pathlib import Path
from typing import Any, cast

import yaml


def test_only_operator_interfaces_have_host_edge_access() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = cast(dict[str, Any], yaml.safe_load((root / "docker-compose.yml").read_text()))
    networks = cast(dict[str, dict[str, Any] | None], compose["networks"])
    services = cast(dict[str, dict[str, Any]], compose["services"])

    assert networks["application"] == {"internal": True}
    assert networks["edge"] is None
    assert services["gateway"]["networks"] == ["application", "evidence", "edge"]
    assert services["grafana"]["networks"] == ["application", "edge"]
    assert services["control-plane"]["networks"] == ["evidence", "edge"]
    assert services["gateway"]["ports"] == ["127.0.0.1:${INCIDENTPILOT_GATEWAY_PORT:-8000}:8000"]
    assert services["grafana"]["ports"] == ["127.0.0.1:3000:3000"]
    assert services["control-plane"]["ports"] == [
        "127.0.0.1:${INCIDENTPILOT_CONTROL_PLANE_PORT:-8001}:8000"
    ]
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


def test_control_plane_has_no_mutation_credentials_or_runtime_control() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = cast(dict[str, Any], yaml.safe_load((root / "docker-compose.yml").read_text()))
    services = cast(dict[str, dict[str, Any]], compose["services"])
    service = services["control-plane"]
    environment = cast(dict[str, str], service["environment"])
    assert not ({"INCIDENTPILOT_DATABASE_URL", "INCIDENTPILOT_BROKER_URL"} & environment.keys())
    assert "application" not in service["networks"]
    assert "evidence" in service["networks"]
    assert "evidence" not in services["postgres"]["networks"]
    assert "evidence" not in services["redis"]["networks"]
    assert not service.get("privileged", False)
    assert "/var/run/docker.sock" not in str(service.get("volumes", []))
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
