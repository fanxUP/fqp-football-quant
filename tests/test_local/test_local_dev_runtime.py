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
