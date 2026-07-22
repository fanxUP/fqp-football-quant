import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_dev_prefers_python314_before_generic_python3() -> None:
    script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")

    explicit_python = script.index('command -v python3.14')
    generic_python = script.index('command -v python3)', explicit_python)

    assert explicit_python < generic_python


def test_python_runtime_is_pinned_to_314_across_project_and_docker() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (PROJECT_ROOT / "ops/Dockerfile.api").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")
    scheduler = (PROJECT_ROOT / "ops/local/run_local_scheduler.sh").read_text(
        encoding="utf-8"
    )
    setup = (PROJECT_ROOT / "ops/local/setup_local_latest_macos.sh").read_text(
        encoding="utf-8"
    )
    environment_check = (
        PROJECT_ROOT / "scripts/local/check_local_environment.py"
    ).read_text(encoding="utf-8")

    assert pyproject["project"]["requires-python"] == ">=3.14,<3.15"
    assert pyproject["tool"]["ruff"]["target-version"] == "py314"
    assert pyproject["tool"]["mypy"]["python_version"] == "3.14"
    assert (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14"
    assert dockerfile.startswith("FROM python:3.14.6\n")
    assert "shap==0.52.0" in requirements
    assert "numba==0.66.0" in requirements
    assert "llvmlite==0.48.0" in requirements
    assert "Python 3.14 is required" in dev
    assert "Python 3.14 is required" in scheduler
    assert "brew install python@3.14" in setup
    assert "sys.version_info[:2] != (3, 14)" in environment_check


def test_hybrid_runtime_uses_the_single_docker_database_and_scheduler() -> None:
    hybrid = (PROJECT_ROOT / "ops/local/run_hybrid_dev.sh").read_text(
        encoding="utf-8"
    )
    override = (PROJECT_ROOT / "ops/local/docker-compose.hybrid.yml").read_text(
        encoding="utf-8"
    )
    env_example = (PROJECT_ROOT / ".env.local.example").read_text(encoding="utf-8")
    dev = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")

    assert "127.0.0.1:5433/fqp" in env_example
    assert "127.0.0.1:5432/fqp" not in env_example
    assert "stop frontend backend" in hybrid
    assert "postgres redis worker scheduler grafana" in hybrid
    assert "run_local_scheduler" not in hybrid
    assert "FQP_DATABASE_URL_OVERRIDE" in hybrid
    assert "FQP_DATABASE_URL_OVERRIDE" in dev
    assert "profiles: [docker-app]" in override
    assert override.count("http://host.docker.internal:8006/health") == 2
