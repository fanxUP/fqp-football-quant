from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_host_ports_use_the_canonical_local_endpoints() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "ops/local/docker-compose.local.yml").read_text(encoding="utf-8")
    )
    deploy_script = (PROJECT_ROOT / "ops/local/run_local_stack.sh").read_text(
        encoding="utf-8"
    )
    dev_script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(
        encoding="utf-8"
    )
    deployment_config = yaml.safe_load(
        (PROJECT_ROOT / "configs/local_personal_deployment.yaml").read_text(
            encoding="utf-8"
        )
    )
    vite_config = (PROJECT_ROOT / "apps/frontend/vite.config.ts").read_text(
        encoding="utf-8"
    )

    assert compose["services"]["frontend"]["ports"] == [
        "127.0.0.1:${FQP_FRONTEND_PORT:-8066}:3000"
    ]
    assert compose["services"]["backend"]["ports"] == [
        "127.0.0.1:${FQP_BACKEND_PORT:-8006}:8000"
    ]
    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in deploy_script
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"' in deploy_script
    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in dev_script
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"' in dev_script
    assert deployment_config["network"]["frontend_port"] == 8066
    assert deployment_config["network"]["backend_port"] == 8006
    assert "port: 8066" in vite_config
    assert "http://127.0.0.1:8006" in vite_config


def test_frontend_has_a_readiness_healthcheck() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "ops/local/docker-compose.local.yml").read_text(encoding="utf-8")
    )

    healthcheck = compose["services"]["frontend"]["healthcheck"]
    command = " ".join(healthcheck["test"])

    assert "http://localhost:3000/" in command
    assert healthcheck["start_period"]
    assert healthcheck["retries"] >= 5


def test_backend_and_scheduler_share_scheduler_heartbeat() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "ops/local/docker-compose.local.yml").read_text(encoding="utf-8")
    )

    for service_name in ("backend", "scheduler"):
        service = compose["services"][service_name]
        assert "../../.runtime:/app/.runtime" in service["volumes"]
        assert service["environment"]["FQP_SCHEDULER_HEARTBEAT_MODE"] == "shared"


def test_deploy_applies_incremental_migrations_before_runtime_contract_check() -> None:
    script = (PROJECT_ROOT / "ops/local/run_local_stack.sh").read_text(encoding="utf-8")

    migration_step = script.index("apply_local_migrations.sh")
    predictions_check = script.index("/api/predictions?limit=1")

    assert migration_step < predictions_check


def test_incremental_migrations_track_applied_files() -> None:
    script = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(encoding="utf-8")

    assert "local_schema_migrations" in script
    assert "ON_ERROR_STOP=1" in script
    assert "BASELINE_VERSION=32" in script
