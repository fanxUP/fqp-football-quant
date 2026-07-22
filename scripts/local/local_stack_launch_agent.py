"""Render the per-user launchd service for the all-local FQP stack."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path
from typing import Any

LABEL = "com.fqp.local-stack"
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def build_launch_agent_plist(project_root: Path) -> dict[str, Any]:
    runtime_dir = project_root / ".runtime"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/bash",
            str(project_root / "ops/local/run_all_local.sh"),
        ],
        "EnvironmentVariables": {"PATH": LAUNCHD_PATH},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 20,
        "StandardOutPath": str(runtime_dir / "local-stack.launchd.out.log"),
        "StandardErrorPath": str(runtime_dir / "local-stack.launchd.err.log"),
    }


def write_launch_agent_plist(target: Path, project_root: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as destination:
        plistlib.dump(build_launch_agent_plist(project_root), destination, sort_keys=False)
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the FQP local stack LaunchAgent")
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    write_launch_agent_plist(args.target, args.project_root)
    print(args.target)


if __name__ == "__main__":
    main()
