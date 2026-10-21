#!/usr/bin/env python3
"""FQP-specific preflight around the shared V4 merge gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"BLOCKED: cannot read valid JSON-compatible control file {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit(f"BLOCKED: control file must contain an object: {path}")
    return value


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def fail(message: str) -> int:
    print(f"BLOCKED: {message}", file=sys.stderr)
    return 1


def check_rows_error(rows: Any, expected_checks: set[str]) -> str | None:
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        return "GitHub reported no checks; refusing to infer success"
    if any(not isinstance(row.get("name"), str) or not row["name"] for row in rows):
        return "GitHub returned a check without a valid name"
    names = {row["name"] for row in rows}
    missing = sorted(expected_checks - names)
    if missing:
        return "configured GitHub checks are missing: " + ", ".join(missing)
    not_passed = sorted(f"{row['name']} ({row.get('bucket', '<missing>')})" for row in rows if row.get("bucket") != "pass")
    if not_passed:
        return "GitHub checks are not green: " + ", ".join(not_passed)
    return None


def verified_engine_sources(engine_path: Path, lock_path: Path) -> dict[str, bytes]:
    """Load only the pinned V4 Python bundle; never execute mutable bytecode."""
    lock = read_json(lock_path)
    expected = lock.get("sha256")
    if not isinstance(expected, dict) or not expected:
        raise SystemExit("BLOCKED: V4 engine lock must contain a non-empty sha256 map")
    engine_dir = engine_path.parent
    if engine_path.name != "vibe.py" or engine_path.is_symlink():
        raise SystemExit("BLOCKED: configured V4 engine must be a regular vibe.py file")
    actual_paths = list(engine_dir.glob("*.py"))
    actual_names = {path.name for path in actual_paths}
    expected_names = set(expected)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(f"BLOCKED: V4 engine bundle file set differs (missing={missing}, extra={extra})")
    sources: dict[str, bytes] = {}
    for path in actual_paths:
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"BLOCKED: V4 engine source must be a regular file: {path}")
        source = path.read_bytes()
        actual_hash = hashlib.sha256(source).hexdigest()
        if actual_hash != expected.get(path.name):
            raise SystemExit(f"BLOCKED: V4 engine source hash mismatch: {path.name}")
        sources[path.name] = source
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    config = read_json(repo / ".vibe/config.yaml")
    policy = config.get("quality_gate", {})
    engine = Path(policy.get("engine_path", "~/.remote-vibe-coding/engine/vibe.py")).expanduser()
    if not engine.is_absolute():
        engine = (repo / engine).resolve()
    repository = policy.get("repository")
    pull_request = policy.get("pull_request")
    if not repository or not isinstance(pull_request, int):
        return fail("configure the GitHub repository and pull request in .vibe/config.yaml")
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
        return fail("launch with an isolated interpreter: python3 -I -S -B .vibe/quality_gate.py")
    gh = shutil.which("gh")
    if gh is None:
        return fail("GitHub CLI (gh) was not found on the trusted local PATH")
    gh_cli = str(Path(gh).resolve())
    try:
        engine_sources = verified_engine_sources(engine, repo / ".vibe/engine-lock.json")
    except SystemExit as exc:
        return fail(str(exc).removeprefix("BLOCKED: "))

    state = read_json(repo / ".vibe/STATE.yaml").get("state")
    if state not in {"REVIEWING", "READY_TO_MERGE"}:
        return fail(f"workflow state must be REVIEWING or READY_TO_MERGE, got {state!r}")

    evidence = read_json(repo / ".vibe/EVIDENCE.yaml")
    tasks = read_json(repo / ".vibe/TASK_DAG.yaml").get("tasks", {})
    acceptances = evidence.get("acceptance", {})
    for task_id, task in tasks.items():
        if task.get("status") not in {"DONE", "PASS", "COMPLETE"}:
            return fail(f"task {task_id} is not complete")
        acceptance_id = task.get("acceptance_id")
        record = acceptances.get(acceptance_id, {})
        if record.get("status") != "PASS":
            return fail(f"acceptance {acceptance_id} is not PASS")

    reviews = evidence.get("reviews", {})
    if reviews.get("status") != "PASS":
        return fail("independent reviews are not PASS")
    for required_review in ("application_code", "v4_migration"):
        if reviews.get(required_review, {}).get("status") != "PASS":
            return fail(f"required review {required_review} is not PASS")
    for name, item in reviews.items():
        if name != "status" and isinstance(item, dict) and item.get("status") != "PASS":
            return fail(f"review {name} is not explicitly PASS")
    if evidence.get("security", {}).get("status") != "PASS":
        return fail("security review is not PASS")
    if evidence.get("migration", {}).get("status") not in {"PASS", "NOT_APPLICABLE"}:
        return fail("migration review is neither PASS nor NOT_APPLICABLE")
    ci = evidence.get("external_ci", {})
    if ci.get("status") != "passed" or not ci.get("checks") or any(v != "passed" for v in ci["checks"].values()):
        return fail("recorded application CI evidence is incomplete")

    dirty = run(["git", "status", "--porcelain"], repo)
    if dirty.returncode or dirty.stdout.strip():
        return fail("checkout must be clean so the approved evidence and controls are committed")
    branch = run(["git", "branch", "--show-current"], repo)
    head = run(["git", "rev-parse", "HEAD"], repo)
    if branch.returncode or head.returncode:
        return fail("cannot determine the current branch and revision")
    pr = run([gh_cli, "pr", "view", str(pull_request), "--repo", repository, "--json", "state,headRefName,baseRefName,headRefOid"], repo)
    if pr.returncode:
        return fail("cannot read the selected GitHub pull request; check gh authentication")
    try:
        pr_data = json.loads(pr.stdout)
    except json.JSONDecodeError:
        return fail("GitHub returned invalid PR metadata")
    if pr_data.get("state") != "OPEN" or pr_data.get("baseRefName") != "main":
        return fail("the selected PR must be open and target main")
    if pr_data.get("headRefName") != branch.stdout.strip() or pr_data.get("headRefOid") != head.stdout.strip():
        return fail("the selected PR head does not match this checkout")

    expected_checks = set(policy.get("required_checks", []))
    if not expected_checks:
        return fail("configure the project-required GitHub checks in .vibe/config.yaml")
    checks = run([gh_cli, "pr", "checks", str(pull_request), "--repo", repository, "--json", "name,bucket"], repo)
    if checks.returncode:
        return fail(f"GitHub checks are not all green (gh exit {checks.returncode})")
    try:
        rows = json.loads(checks.stdout)
    except json.JSONDecodeError:
        return fail("GitHub returned invalid check data")
    check_error = check_rows_error(rows, expected_checks)
    if check_error:
        return fail(check_error)
    final_pr = run([gh_cli, "pr", "view", str(pull_request), "--repo", repository, "--json", "state,headRefName,baseRefName,headRefOid"], repo)
    if final_pr.returncode:
        return fail("cannot re-read the selected PR after checking its CI status")
    try:
        final_pr_data = json.loads(final_pr.stdout)
    except json.JSONDecodeError:
        return fail("GitHub returned invalid final PR metadata")
    if (
        final_pr_data.get("state") != "OPEN"
        or final_pr_data.get("baseRefName") != "main"
        or final_pr_data.get("headRefName") != branch.stdout.strip()
        or final_pr_data.get("headRefOid") != head.stdout.strip()
        or final_pr_data.get("headRefOid") != pr_data.get("headRefOid")
    ):
        return fail("PR head or base changed while checking CI; re-run the preflight")
    final_branch = run(["git", "branch", "--show-current"], repo)
    final_head = run(["git", "rev-parse", "HEAD"], repo)
    final_dirty = run(["git", "status", "--porcelain"], repo)
    if (
        final_branch.returncode
        or final_head.returncode
        or final_dirty.returncode
        or final_branch.stdout.strip() != branch.stdout.strip()
        or final_head.stdout.strip() != head.stdout.strip()
        or final_dirty.stdout.strip()
    ):
        return fail("local branch, revision, or worktree changed during preflight; re-run it")
    print("PASS: required reviews, security, migration, task acceptance, and configured live PR checks")

    # Execute a clean temporary copy so modified or stale __pycache__ files beside
    # the configured engine cannot bypass the source hash lock.
    with tempfile.TemporaryDirectory(prefix="fqp-v4-engine-") as temp_dir:
        isolated_engine = Path(temp_dir)
        for name, source in engine_sources.items():
            (isolated_engine / name).write_bytes(source)
        gate = run([sys.executable, "-I", "-S", "-B", str(isolated_engine / "vibe.py"), "--repo", str(repo), "gate", "merge"], repo)
    sys.stdout.write(gate.stdout)
    sys.stderr.write(gate.stderr)
    if gate.returncode:
        return gate.returncode
    if "QUALITY GATE: READY_TO_MERGE" not in gate.stdout:
        return fail("V4 engine did not report READY_TO_MERGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
