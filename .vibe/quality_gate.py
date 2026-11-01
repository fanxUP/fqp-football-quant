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
        raise SystemExit(
            f"BLOCKED: cannot read valid JSON-compatible control file {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise SystemExit(f"BLOCKED: control file must contain an object: {path}")
    return value


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def fail(message: str) -> int:
    print(f"BLOCKED: {message}", file=sys.stderr)
    return 1


def main_ref_error(
    current_branch: str, required_branch: str, head_sha: str, remote_sha: str
) -> str | None:
    if required_branch != "main":
        return "single-branch policy requires main as the release branch"
    if current_branch != required_branch:
        return f"checkout must be on {required_branch}; got {current_branch or '<detached>'}"
    if not head_sha or remote_sha != head_sha:
        return "GitHub main does not point to the exact local release commit"
    return None


def select_main_ci_run(
    runs: Any, head_sha: str, branch: str, workflow_name: str
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        return None, "GitHub returned an invalid CI run list"
    matching = [
        run
        for run in runs
        if run.get("headSha") == head_sha
        and run.get("headBranch") == branch
        and run.get("event") == "push"
        and run.get("workflowName") == workflow_name
    ]
    if not matching:
        return None, f"no {workflow_name} push CI run exists for {branch}@{head_sha}"
    latest = max(matching, key=lambda run: str(run.get("createdAt", "")))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        return None, (
            "latest matching main CI run is not successful "
            f"(status={latest.get('status', '<missing>')}, "
            f"conclusion={latest.get('conclusion', '<missing>')})"
        )
    if not isinstance(latest.get("databaseId"), int):
        return None, "GitHub returned a matching CI run without a valid database ID"
    return latest, None


def check_job_results(jobs: Any, expected_checks: set[str]) -> str | None:
    if not isinstance(jobs, list) or not jobs or any(not isinstance(job, dict) for job in jobs):
        return "GitHub reported no CI jobs; refusing to infer success"
    if any(not isinstance(job.get("name"), str) or not job["name"] for job in jobs):
        return "GitHub returned a CI job without a valid name"
    by_name = {job["name"]: job for job in jobs}
    missing = sorted(expected_checks - by_name.keys())
    if missing:
        return "configured GitHub checks are missing: " + ", ".join(missing)
    not_passed = sorted(
        f"{name} (status={by_name[name].get('status', '<missing>')}, "
        f"conclusion={by_name[name].get('conclusion', '<missing>')})"
        for name in expected_checks
        if by_name[name].get("status") != "completed"
        or by_name[name].get("conclusion") != "success"
    )
    if not_passed:
        return "configured GitHub checks are not green: " + ", ".join(not_passed)
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
        raise SystemExit(
            f"BLOCKED: V4 engine bundle file set differs (missing={missing}, extra={extra})"
        )
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
    required_branch = policy.get("required_branch")
    workflow_name = policy.get("required_workflow")
    if not repository or not isinstance(required_branch, str) or not workflow_name:
        return fail(
            "configure the GitHub repository, required main branch and workflow in .vibe/config.yaml"
        )
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
    if (
        ci.get("status") != "passed"
        or not ci.get("checks")
        or any(v != "passed" for v in ci["checks"].values())
    ):
        return fail("recorded application CI evidence is incomplete")

    dirty = run(["git", "status", "--porcelain"], repo)
    if dirty.returncode or dirty.stdout.strip():
        return fail("checkout must be clean so the approved evidence and controls are committed")
    branch = run(["git", "branch", "--show-current"], repo)
    head = run(["git", "rev-parse", "HEAD"], repo)
    if branch.returncode or head.returncode:
        return fail("cannot determine the current branch and revision")
    head_sha = head.stdout.strip()
    ref = run(
        [
            gh_cli,
            "api",
            f"repos/{repository}/git/ref/heads/{required_branch}",
            "--jq",
            ".object.sha",
        ],
        repo,
    )
    if ref.returncode:
        return fail("cannot read the configured GitHub main ref; check gh authentication")
    ref_error = main_ref_error(branch.stdout.strip(), required_branch, head_sha, ref.stdout.strip())
    if ref_error:
        return fail(ref_error)
    runs_result = run(
        [
            gh_cli,
            "run",
            "list",
            "--repo",
            repository,
            "--branch",
            required_branch,
            "--commit",
            head_sha,
            "--json",
            "databaseId,headSha,headBranch,event,status,conclusion,workflowName,createdAt",
            "--limit",
            "100",
        ],
        repo,
    )
    if runs_result.returncode:
        return fail("cannot read GitHub Actions runs for the current main commit")
    try:
        runs = json.loads(runs_result.stdout)
    except json.JSONDecodeError:
        return fail("GitHub returned invalid Actions run data")

    expected_checks = set(policy.get("required_checks", []))
    if not expected_checks:
        return fail("configure the project-required GitHub checks in .vibe/config.yaml")
    selected_run, run_error = select_main_ci_run(runs, head_sha, required_branch, workflow_name)
    if run_error or not selected_run:
        return fail(run_error or "GitHub has no matching main CI run")
    jobs_result = run(
        [
            gh_cli,
            "run",
            "view",
            str(selected_run["databaseId"]),
            "--repo",
            repository,
            "--json",
            "jobs",
        ],
        repo,
    )
    if jobs_result.returncode:
        return fail("cannot read jobs for the latest matching main CI run")
    try:
        jobs_data = json.loads(jobs_result.stdout)
    except json.JSONDecodeError:
        return fail("GitHub returned invalid CI job data")
    if not isinstance(jobs_data, dict):
        return fail("GitHub returned invalid CI job data")
    jobs = jobs_data.get("jobs")
    check_error = check_job_results(jobs, expected_checks)
    if check_error:
        return fail(check_error)
    final_ref = run(
        [
            gh_cli,
            "api",
            f"repos/{repository}/git/ref/heads/{required_branch}",
            "--jq",
            ".object.sha",
        ],
        repo,
    )
    if final_ref.returncode or final_ref.stdout.strip() != head_sha:
        return fail("GitHub main changed while checking CI; re-run the preflight")
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
    print(
        "PASS: required reviews, security, migration, task acceptance, and configured live main CI checks"
    )

    # Execute a clean temporary copy so modified or stale __pycache__ files beside
    # the configured engine cannot bypass the source hash lock.
    with tempfile.TemporaryDirectory(prefix="fqp-v4-engine-") as temp_dir:
        isolated_engine = Path(temp_dir)
        for name, source in engine_sources.items():
            (isolated_engine / name).write_bytes(source)
        gate = run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(isolated_engine / "vibe.py"),
                "--repo",
                str(repo),
                "gate",
                "merge",
            ],
            repo,
        )
    sys.stdout.write(gate.stdout)
    sys.stderr.write(gate.stderr)
    if gate.returncode:
        return gate.returncode
    if "QUALITY GATE: READY_TO_MERGE" not in gate.stdout:
        return fail("V4 engine did not report READY_TO_MERGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
