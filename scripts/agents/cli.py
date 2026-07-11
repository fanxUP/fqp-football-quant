"""Small local CLI for auditable multi-agent task operations."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from apps.backend.src.db import get_db
from scripts.agent_storage import (
    add_task_artifact,
    create_review_report,
    finish_job_run,
    retry_job_run,
    resolve_review_gate,
    start_job_run,
)
from scripts.agents.task_queue import check_job_dependencies
from scripts.agents.agent_registry import seed_from_yaml
from scripts.agents.orchestrator import AgentTask, create_task, transition_task


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fqp-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-agents")
    create = sub.add_parser("create-task")
    create.add_argument("task_code")
    create.add_argument("task_title")
    create.add_argument("owner_agent")
    create.add_argument("--task-type", default="general")
    create.add_argument("--risk-level", default="L2")
    transition = sub.add_parser("transition")
    transition.add_argument("task_code")
    transition.add_argument("status")
    transition.add_argument("--summary", default="")
    artifact = sub.add_parser("add-artifact")
    artifact.add_argument("task_id", type=int)
    artifact.add_argument("artifact_path")
    artifact.add_argument("--artifact-type", default="output")
    artifact.add_argument("--summary", default="")
    qa = sub.add_parser("qa-report")
    qa.add_argument("task_id", type=int)
    qa.add_argument("test_command")
    qa.add_argument("--passed", type=int, default=0)
    qa.add_argument("--failed", type=int, default=0)
    qa.add_argument("--summary", default="")
    job = sub.add_parser("job-start")
    job.add_argument("job_code")
    job.add_argument("owner_agent")
    job.add_argument("--job-name", default=None)
    job.add_argument("--depends-on", action="append", default=[])
    job_finish = sub.add_parser("job-finish")
    job_finish.add_argument("run_id", type=int)
    job_finish.add_argument("status", choices=("completed", "failed", "blocked"))
    job_finish.add_argument("--error", default=None)
    job_retry = sub.add_parser("job-retry")
    job_retry.add_argument("run_id", type=int)
    job_retry.add_argument("--max-retries", type=int, default=2)
    gate = sub.add_parser("review-resolve")
    gate.add_argument("gate_id", type=int)
    gate.add_argument("reviewer")
    gate.add_argument("status", choices=("approved", "rejected"))
    gate.add_argument("--comment", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "seed-agents":
        print(seed_from_yaml())
    elif args.command == "create-task":
        print(create_task(AgentTask(
            task_code=args.task_code, task_title=args.task_title,
            owner_agent=args.owner_agent, task_type=args.task_type,
            risk_level=args.risk_level,
        )))
    elif args.command == "transition":
        print(transition_task(args.task_code, args.status, args.summary))
    elif args.command == "add-artifact":
        path = Path(args.artifact_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        with get_db() as conn:
            artifact_id = add_task_artifact(conn, {
                "task_id": args.task_id, "artifact_type": args.artifact_type,
                "artifact_path": str(path), "artifact_summary": args.summary,
                "artifact_hash": digest,
            })
        print({"artifact_id": artifact_id, "artifact_hash": digest})
    elif args.command == "qa-report":
        with get_db() as conn:
            report_id = create_review_report(conn, {
                "task_id": args.task_id, "report_type": "qa",
                "test_command": args.test_command, "pass_count": args.passed,
                "fail_count": args.failed,
                "report_json": {"summary": args.summary, "status": "passed" if args.failed == 0 else "failed"},
            })
        print({"report_id": report_id, "status": "passed" if args.failed == 0 else "failed"})
    elif args.command == "job-start":
        check_job_dependencies(args.depends_on)
        with get_db() as conn:
            run_id = start_job_run(conn, {
                "job_code": args.job_code, "job_name": args.job_name or args.job_code,
                "owner_agent": args.owner_agent, "schedule_type": "manual",
                "environment": "local",
                "input_snapshot_refs": {"dependencies": args.depends_on} if args.depends_on else {},
            })
        print({"run_id": run_id, "status": "running"})
    elif args.command == "job-finish":
        with get_db() as conn:
            ok = finish_job_run(conn, args.run_id, args.status, error=args.error)
        print({"run_id": args.run_id, "updated": ok, "status": args.status})
    elif args.command == "job-retry":
        with get_db() as conn:
            ok = retry_job_run(conn, args.run_id, max_retries=args.max_retries)
        print({"run_id": args.run_id, "retried": ok})
    elif args.command == "review-resolve":
        with get_db() as conn:
            ok = resolve_review_gate(
                conn, args.gate_id, args.reviewer, args.status, args.comment
            )
        print({"gate_id": args.gate_id, "resolved": ok, "status": args.status})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
