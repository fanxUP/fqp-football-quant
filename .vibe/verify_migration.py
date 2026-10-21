#!/usr/bin/env python3
"""Reproducibly verify the P118 archive and V4 control migration."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_gate import verified_engine_sources


ROOT = Path(__file__).resolve().parent.parent
VIBE = ROOT / ".vibe"
EXPECTED_ARCHIVE_FILES = frozenset(
    {
        "ACCEPTANCE.md",
        "BASELINE.yaml",
        "CHANGE_BUDGET.yaml",
        "DESIGN.md",
        "EVIDENCE.json",
        "PLAN.md",
        "SCOPE_LOCK.yaml",
        "TASK_DAG.yaml",
        "releases/2026-10-16-cleanup.md",
    }
)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"FAIL: expected JSON object: {path}")
    return value


def main() -> int:
    control_names = [
        "STATE.yaml",
        "EVIDENCE.yaml",
        "SCOPE_LOCK.yaml",
        "CHANGE_BUDGET.yaml",
        "BASELINE.yaml",
        "TASK_DAG.yaml",
        "config.yaml",
        "engine-lock.json",
    ]
    for name in control_names:
        read_json(VIBE / name)

    archive = VIBE / "archive/pre-v4-p118-2026-10-21"
    manifest = read_json(archive / "MANIFEST.json")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("FAIL: archive manifest contains no file hashes")
    manifest_paths = [entry.get("path") for entry in files if isinstance(entry, dict)]
    if (
        len(manifest_paths) != len(files)
        or any(not isinstance(path, str) for path in manifest_paths)
        or len(set(manifest_paths)) != len(manifest_paths)
    ):
        raise SystemExit("FAIL: archive manifest has invalid or duplicate entries")
    if set(manifest_paths) != EXPECTED_ARCHIVE_FILES:
        raise SystemExit("FAIL: archive manifest does not contain the exact pre-V4 file set")
    actual_paths: set[str] = set()
    archive_root = archive.resolve()
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"FAIL: archive must not contain symlinks: {path.relative_to(archive)}")
        if path.is_file() and path != archive / "MANIFEST.json":
            actual_paths.add(path.relative_to(archive).as_posix())
    if actual_paths != EXPECTED_ARCHIVE_FILES:
        raise SystemExit("FAIL: archive has missing or unexpected files")
    for entry in files:
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise SystemExit(f"FAIL: unsafe archive path in manifest: {rel}")
        path = archive / rel
        if path.is_symlink() or not path.resolve().is_relative_to(archive_root):
            raise SystemExit(f"FAIL: archived path escapes its root or is a symlink: {rel}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            raise SystemExit(f"FAIL: archived file hash mismatch: {rel}")

    old = read_json(archive / "EVIDENCE.json")
    for key in ("current_task", "current_slice", "current_status"):
        if manifest.get(f"legacy_{key}") != old.get(key):
            raise SystemExit(f"FAIL: manifest does not preserve legacy {key}")
    if old.get("current_task") != "P118" or "evidence_update_ci_pending" not in old.get("current_status", ""):
        raise SystemExit("FAIL: archived P118 status is not preserved as pending")

    config = read_json(VIBE / "config.yaml")
    engine_path = Path(config["quality_gate"]["engine_path"]).expanduser()
    if not engine_path.is_absolute():
        engine_path = (ROOT / engine_path).resolve()
    sources = verified_engine_sources(engine_path, VIBE / "engine-lock.json")
    print(
        f"PASS: {len(files)} archived files hash-verified; {len(control_names)} V4 controls parse; "
        f"P118 pending status preserved; {len(sources)} pinned engine sources verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
