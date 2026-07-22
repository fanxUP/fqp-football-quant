"""Supervise the four host application processes without Docker Desktop."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path


def build_process_specs(
    *,
    python_bin: str,
    backend_port: int,
    frontend_port: int,
) -> tuple[ProcessSpec, ...]:
    """Return the independently supervised host process definitions."""
    return (
        ProcessSpec(
            "backend",
            (
                python_bin,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(backend_port),
                "--reload",
            ),
            ROOT,
        ),
        ProcessSpec(
            "frontend",
            (
                "npm",
                "--prefix",
                str(ROOT / "apps/frontend"),
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(frontend_port),
            ),
            ROOT,
        ),
        ProcessSpec(
            "worker",
            (python_bin, "-u", "-m", "scripts.official_crawler_stub"),
            ROOT,
        ),
        ProcessSpec(
            "scheduler",
            (python_bin, "-u", "-m", "scripts.jobs.run_scheduler"),
            ROOT,
        ),
    )


def _start(spec: ProcessSpec, environment: dict[str, str]) -> subprocess.Popen[bytes]:
    print(f"[fqp-local-stack] starting {spec.name}", flush=True)
    return subprocess.Popen(
        spec.command,
        cwd=spec.cwd,
        env=environment,
        start_new_session=True,
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> None:
    backend_port = int(os.getenv("FQP_BACKEND_PORT", "8006"))
    frontend_port = int(os.getenv("FQP_FRONTEND_PORT", "8066"))
    python_bin = os.getenv("FQP_PYTHON_BIN", sys.executable)
    specs = build_process_specs(
        python_bin=python_bin,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )
    environment = os.environ.copy()
    environment.update(
        {
            "FQP_ODDS_DISPATCH_OWNER": "worker",
            "FQP_SCHEDULER_HEARTBEAT_MODE": "local",
            "FQP_API_HEALTH_URL": f"http://127.0.0.1:{backend_port}/health",
            "VITE_PROXY_TARGET": f"http://127.0.0.1:{backend_port}",
        }
    )

    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    processes = {spec.name: _start(spec, environment) for spec in specs}
    try:
        while not stop_requested:
            for spec in specs:
                process = processes[spec.name]
                exit_code = process.poll()
                if exit_code is None:
                    continue
                print(
                    f"[fqp-local-stack] {spec.name} exited ({exit_code}); restarting",
                    flush=True,
                )
                time.sleep(2)
                if stop_requested:
                    break
                processes[spec.name] = _start(spec, environment)
            time.sleep(1)
    finally:
        for spec in reversed(specs):
            _stop(processes[spec.name])


if __name__ == "__main__":
    main()
