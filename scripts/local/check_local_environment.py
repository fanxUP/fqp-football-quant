"""Check the local toolchain and enforce the project's Python 3.14 runtime."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "runtime_version_snapshot.json"

COMMANDS = {
    "git": ["git", "--version"],
    "python": [sys.executable, "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "postgresql": ["/opt/homebrew/opt/postgresql@18/bin/psql", "--version"],
    "redis": ["/opt/homebrew/opt/redis/bin/redis-server", "--version"],
    "codex": ["codex", "--version"],
}


def run(cmd: list[str]) -> dict:
    exe = cmd[0]
    if shutil.which(exe) is None:
        return {"installed": False, "version": None, "error": f"{exe} not found"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {
            "installed": p.returncode == 0,
            "version": (p.stdout or p.stderr).strip(),
            "error": None if p.returncode == 0 else (p.stderr or p.stdout).strip(),
        }
    except Exception as exc:
        return {"installed": False, "version": None, "error": str(exc)}


def main() -> None:
    if sys.version_info[:2] != (3, 14):
        raise SystemExit(
            f"Python 3.14 is required; current runtime is {sys.version_info.major}.{sys.version_info.minor}."
        )

    snapshot: dict[str, Any] = {"generated_at": datetime.now().isoformat(timespec="seconds"), "components": {}}
    for name, cmd in COMMANDS.items():
        snapshot["components"][name] = run(cmd)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    missing = [k for k, v in snapshot["components"].items() if not v["installed"]]
    if missing:
        print("Missing components:", ", ".join(missing))
        print("Install missing components from their official latest installation channels.")
    else:
        print("All checked components are available. Python runtime is 3.14.")


if __name__ == "__main__":
    main()
