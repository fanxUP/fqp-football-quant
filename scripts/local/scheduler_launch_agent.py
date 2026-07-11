"""Render the per-user launchd service for the local FQP scheduler."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path
from typing import Any

LABEL = "com.fqp.scheduler"


def build_launch_agent_plist(project_root: Path) -> dict[str, Any]:
    """Build a launchd plist with paths resolved for one local checkout."""
    runtime_dir = project_root / ".runtime"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(project_root / "ops/local/run_local_scheduler.sh")],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(runtime_dir / "scheduler.launchd.out.log"),
        "StandardErrorPath": str(runtime_dir / "scheduler.launchd.err.log"),
    }


def write_launch_agent_plist(target: Path, project_root: Path) -> None:
    """Write the launchd plist atomically for the current local user."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as destination:
        plistlib.dump(build_launch_agent_plist(project_root), destination, sort_keys=False)
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the local FQP scheduler LaunchAgent")
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    write_launch_agent_plist(args.target, args.project_root)
    print(args.target)


if __name__ == "__main__":
    main()
