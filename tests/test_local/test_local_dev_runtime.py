import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_dev_prefers_python314_before_generic_python3() -> None:
    script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")

    explicit_python = script.index("command -v python3.14")
    generic_python = script.index("command -v python3)", explicit_python)

    assert explicit_python < generic_python


def test_python_runtime_is_pinned_to_314_across_project() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")
    scheduler = (PROJECT_ROOT / "ops/local/run_local_scheduler.sh").read_text(encoding="utf-8")
    setup = (PROJECT_ROOT / "ops/local/setup_local_latest_macos.sh").read_text(encoding="utf-8")
    environment_check = (PROJECT_ROOT / "scripts/local/check_local_environment.py").read_text(
        encoding="utf-8"
    )

    assert pyproject["project"]["requires-python"] == ">=3.14,<3.15"
    assert pyproject["tool"]["ruff"]["target-version"] == "py314"
    assert pyproject["tool"]["mypy"]["python_version"] == "3.14"
    assert (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14"
    assert "shap==0.52.0" in requirements
    assert "numba==0.66.0" in requirements
    assert "llvmlite==0.48.0" in requirements
    assert "Python 3.14 is required" in dev
    assert "Python 3.14 is required" in scheduler
    assert "brew install python@3.14" in setup
    assert "sys.version_info[:2] != (3, 14)" in environment_check


def test_all_host_defaults_target_native_postgres() -> None:
    env_example = (PROJECT_ROOT / ".env.local.example").read_text(encoding="utf-8")
    executable_paths = (
        PROJECT_ROOT / "apps/backend/src/db.py",
        PROJECT_ROOT / "ops/backup_daily.sh",
        PROJECT_ROOT / "scripts/jobs/verify_backup.py",
    )

    assert "127.0.0.1:5432/fqp" in env_example
    assert "127.0.0.1:5433/fqp" not in env_example
    for path in executable_paths:
        content = path.read_text(encoding="utf-8")
        assert "127.0.0.1:5432/fqp" in content
        assert "127.0.0.1:5433/fqp" not in content


def test_local_scheduler_has_one_owner_for_odds_and_local_heartbeat() -> None:
    scheduler = (PROJECT_ROOT / "ops/local/run_local_scheduler.sh").read_text(encoding="utf-8")

    assert "FQP_SCHEDULER_HEARTBEAT_MODE=local" in scheduler
    assert "FQP_ODDS_DISPATCH_OWNER=worker" in scheduler


def test_macos_setup_installs_native_dependencies() -> None:
    setup = (PROJECT_ROOT / "ops/local/setup_local_latest_macos.sh").read_text(encoding="utf-8")

    assert "brew install postgresql@18" in setup
    assert "brew install redis" in setup
    assert "brew services start postgresql@18" in setup
    assert "brew services start redis" in setup
