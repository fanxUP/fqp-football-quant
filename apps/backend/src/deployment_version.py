"""Resolve the deployment identifier for the code serving this process."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _load_release_id() -> str:
    try:
        deployed = (_PROJECT_ROOT / ".runtime" / "release-id").read_text(encoding="utf-8").strip()
    except OSError:
        deployed = ""
    if deployed and _RELEASE_ID_PATTERN.fullmatch(deployed):
        return deployed

    configured = os.getenv("FQP_RELEASE_ID", "").strip()
    if configured and _RELEASE_ID_PATTERN.fullmatch(configured):
        return configured

    try:
        result = subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        commit = result.stdout.strip()
        if re.fullmatch(r"[0-9a-f]{40}", commit):
            return commit
    except OSError, subprocess.SubprocessError:
        pass

    try:
        version = (_PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"
    return f"version-{version or 'unknown'}"


RELEASE_ID = _load_release_id()
