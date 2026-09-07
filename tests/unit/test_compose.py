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
    assert services["gateway"]["ports"] == ["127.0.0.1:8000:8000"]
    for name in {"auth", "data", "worker", "migrate", "postgres", "redis"}:
        assert "edge" not in services[name].get("networks", [])
        assert "ports" not in services[name]
