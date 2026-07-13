from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_dev_prefers_python311_before_generic_python3() -> None:
    script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")

    explicit_python = script.index('command -v python3.11')
    generic_python = script.index('command -v python3)', explicit_python)

    assert explicit_python < generic_python
