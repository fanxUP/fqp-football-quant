"""Runtime version snapshot job.

Stage 8: Records the current runtime environment versions at startup and
periodically (weekly). Writes to data/runtime_version_snapshot.json as
specified in doc 52.

Non-pinning: this records what IS installed, not what SHOULD be installed.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.business_time import utc_now_iso


def _now(value: datetime | None = None) -> str:
    return utc_now_iso(value)


def _check_command(cmd: list[str]) -> dict:
    """Check if a command is available and get its version."""
    exe = cmd[0]
    if shutil.which(exe) is None:
        return {"installed": False, "version": None, "error": f"{exe} not found"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {
            "installed": p.returncode == 0,
            "version": (p.stdout or p.stderr).strip().split("\n")[0],
            "error": None if p.returncode == 0 else (p.stderr or p.stdout).strip(),
        }
    except Exception as exc:
        return {"installed": False, "version": None, "error": str(exc)}


def _get_python_packages() -> dict:
    """Get installed Python package versions."""
    try:
        p = subprocess.run(
            ["python", "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if p.returncode == 0:
            packages = json.loads(p.stdout)
            return {pkg["name"]: pkg["version"] for pkg in packages}
    except Exception:
        pass
    return {}


def _get_system_info() -> dict:
    """Get basic system information."""
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def run() -> dict[str, Any]:
    """Generate runtime version snapshot.

    Returns the snapshot dict.
    """
    commands = {
        "postgresql": ["/opt/homebrew/opt/postgresql@18/bin/psql", "--version"],
        "redis": ["/opt/homebrew/opt/redis/bin/redis-server", "--version"],
        "git": ["git", "--version"],
        "python": ["python", "--version"],
        "python3": ["python3", "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
    }

    snapshot: dict[str, Any] = {
        "generated_at": _now(),
        "project": "fqp",
        "system": _get_system_info(),
        "components": {},
        "python_packages": _get_python_packages(),
        "environment_variables": {
            k: v
            for k, v in sorted(os.environ.items())
            if any(
                prefix in k.upper()
                for prefix in [
                    "FQP_",
                    "DATABASE_",
                    "REDIS_",
                    "SPORTTERY_",
                    "FOOTBALL_",
                    "API_",
                    "THEODDS_",
                ]
            )
        },
    }

    for name, cmd in commands.items():
        snapshot["components"][name] = _check_command(cmd)

    # Write to data directory
    root = Path(__file__).resolve().parents[2]
    out_path = root / "data" / "runtime_version_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    missing = [k for k, v in snapshot["components"].items() if not v["installed"]]
    if missing:
        print(f"[snapshot_runtime] Missing components: {', '.join(missing)}")

    return {
        "status": "ok",
        "output_file": str(out_path),
        "components_checked": len(commands),
        "missing": missing,
        "generated_at": snapshot["generated_at"],
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
