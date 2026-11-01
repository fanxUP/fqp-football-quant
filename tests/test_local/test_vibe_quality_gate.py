import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fqp_vibe_quality_gate", ROOT / ".vibe" / "quality_gate.py"
)
assert SPEC and SPEC.loader
quality_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality_gate)


def test_main_preflight_requires_only_the_configured_main_branch_and_remote_head():
    assert quality_gate.main_ref_error("main", "main", "abc123", "abc123") is None
    assert "main" in quality_gate.main_ref_error("feature/task", "main", "abc123", "abc123")
    assert "GitHub main" in quality_gate.main_ref_error("main", "main", "abc123", "def456")


def test_main_preflight_selects_successful_push_ci_for_exact_sha():
    runs = [
        {
            "databaseId": 11,
            "headSha": "abc123",
            "headBranch": "main",
            "event": "pull_request",
            "workflowName": "CI",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-11-01T10:00:00Z",
        },
        {
            "databaseId": 12,
            "headSha": "abc123",
            "headBranch": "main",
            "event": "push",
            "workflowName": "CI",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-11-01T11:00:00Z",
        },
        {
            "databaseId": 13,
            "headSha": "older",
            "headBranch": "main",
            "event": "push",
            "workflowName": "CI",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-11-01T12:00:00Z",
        },
    ]

    selected, error = quality_gate.select_main_ci_run(runs, "abc123", "main", "CI")

    assert error is None
    assert selected and selected["databaseId"] == 12


def test_main_preflight_rejects_latest_failed_or_missing_push_ci():
    runs = [
        {
            "databaseId": 12,
            "headSha": "abc123",
            "headBranch": "main",
            "event": "push",
            "workflowName": "CI",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-11-01T11:00:00Z",
        },
        {
            "databaseId": 14,
            "headSha": "abc123",
            "headBranch": "main",
            "event": "push",
            "workflowName": "CI",
            "status": "completed",
            "conclusion": "failure",
            "createdAt": "2026-11-01T12:00:00Z",
        },
    ]

    selected, error = quality_gate.select_main_ci_run(runs, "abc123", "main", "CI")
    assert selected is None
    assert "failure" in error

    selected, error = quality_gate.select_main_ci_run(runs, "other", "main", "CI")
    assert selected is None
    assert "no" in error.lower()


def test_main_preflight_requires_all_configured_ci_jobs_to_pass():
    jobs = [
        {"name": "test", "status": "completed", "conclusion": "success"},
        {
            "name": "lint-and-typecheck",
            "status": "completed",
            "conclusion": "success",
        },
    ]
    assert quality_gate.check_job_results(jobs, {"test", "lint-and-typecheck"}) is None
    assert "lint-and-typecheck" in quality_gate.check_job_results(
        jobs[:1], {"test", "lint-and-typecheck"}
    )

    jobs[1]["conclusion"] = "failure"
    assert "failure" in quality_gate.check_job_results(jobs, {"test", "lint-and-typecheck"})
