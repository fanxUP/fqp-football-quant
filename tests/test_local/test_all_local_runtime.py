import plistlib
from pathlib import Path

from scripts.local.local_process_supervisor import build_process_specs
from scripts.local.local_stack_launch_agent import build_launch_agent_plist

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_supervisor_assigns_one_owner_per_runtime_process() -> None:
    specs = build_process_specs(
        python_bin="/project/.venv/bin/python",
        backend_port=8006,
        frontend_port=8066,
    )

    assert [spec.name for spec in specs] == [
        "backend",
        "frontend",
        "worker",
        "scheduler",
    ]
    assert len({spec.name for spec in specs}) == len(specs)
    assert "scripts.official_crawler_stub" in specs[2].command
    assert "scripts.jobs.run_scheduler" in specs[3].command


def test_local_launch_agent_restarts_the_supervisor(tmp_path) -> None:
    plist = build_launch_agent_plist(tmp_path / "fqp")

    assert plist["Label"] == "com.fqp.local-stack"
    assert plist["ProgramArguments"][0] == "/bin/bash"
    assert plist["ProgramArguments"][1].endswith("ops/local/run_all_local.sh")
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    plistlib.dumps(plist)


def test_local_runner_requires_native_database_and_owns_odds_dispatch() -> None:
    runner = (PROJECT_ROOT / "ops/local/run_all_local.sh").read_text(encoding="utf-8")
    assert "127.0.0.1:5432/fqp" in runner
    assert "127.0.0.1:5433/fqp" not in runner
    assert "FQP_ODDS_DISPATCH_OWNER=worker" in runner
    assert "FQP_SCHEDULER_HEARTBEAT_MODE=local" in runner


def test_local_manager_applies_migrations_before_launching_runtime() -> None:
    manager = (PROJECT_ROOT / "ops/local/manage_local_stack.sh").read_text(
        encoding="utf-8"
    )

    migration = manager.index('"$SCRIPT_DIR/apply_local_migrations.sh"')
    launch_agent = manager.index("scripts.local.local_stack_launch_agent")
    assert migration < launch_agent
    assert '--max-time 10 "http://127.0.0.1:${BACKEND_PORT}/health"' in manager
