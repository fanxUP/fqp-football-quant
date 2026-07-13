from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_has_a_readiness_healthcheck() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "ops/local/docker-compose.local.yml").read_text(encoding="utf-8")
    )

    healthcheck = compose["services"]["frontend"]["healthcheck"]
    command = " ".join(healthcheck["test"])

    assert "http://localhost:3000/" in command
    assert healthcheck["start_period"]
    assert healthcheck["retries"] >= 5
