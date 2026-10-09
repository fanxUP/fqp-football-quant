"""Read-only, bounded views of existing execution records; never export raw JSON/logs."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from apps.backend.src.services.pipeline_status import utc_iso
from scripts.agent_storage import list_agent_tasks, list_agents, list_job_runs
from scripts.local.scheduler_heartbeat import get_scheduler_status

_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
_ID_KEYS = {
    "match_id",
    "model_version_id",
    "feature_snapshot_id",
    "odds_snapshot_id",
    "snapshot_id",
    "prediction_id",
    "ticket_id",
    "backtest_run_id",
}
_COUNT_KEYS = {
    "count",
    "predictions",
    "votes",
    "matches_processed",
    "snapshots",
    "inserted",
    "updated",
    "skipped",
    "errors",
    "collected",
    "settled",
    "features_built",
}
_STATUSES = {
    "created",
    "queued",
    "assigned",
    "running",
    "in_progress",
    "waiting_review",
    "blocked",
    "failed",
    "passed_tests",
    "approved",
    "rejected",
    "merged",
    "closed",
    "completed",
    "cancelled",
    "ok",
    "success",
    "error",
    "partial",
    "skipped",
    "waiting",
    "no_data",
    "pending",
}


def _number(value: Any, positive: bool = False) -> bool:
    return (
        type(value) in (int, float)
        and 0 <= value <= 9_007_199_254_740_991
        and math.isfinite(value)
        and (not positive or (type(value) is int and value > 0))
    )


def project_refs(value: Any, nested: bool = False) -> dict[str, Any]:
    """Allow numerical record references/counts and explicit job-code dependencies only."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _ID_KEYS | _COUNT_KEYS:
        item = value.get(key)
        if _number(item, positive=key in _ID_KEYS):
            result[key] = item
    for singular in _ID_KEYS:
        key = singular + "s"
        items = value.get(key)
        if isinstance(items, list):
            valid = list(dict.fromkeys(item for item in items[:128] if _number(item, True)))[:32]
            if valid:
                result[key] = valid
    dependencies = value.get("dependencies")
    if isinstance(dependencies, list):
        valid_codes = list(
            dict.fromkeys(
                code
                for code in dependencies[:128]
                if isinstance(code, str) and _CODE.fullmatch(code)
            )
        )[:32]
        if valid_codes:
            result["dependencies"] = valid_codes
    if isinstance(value.get("status"), str) and value["status"] in _STATUSES:
        result["status"] = value["status"]
    if type(value.get("dry_run")) is bool:
        result["dry_run"] = value["dry_run"]
    if not nested:
        child = project_refs(value.get("result"), nested=True)
        if child:
            result["result"] = child
    return result


def _code(value: Any) -> str:
    return value if isinstance(value, str) and _CODE.fullmatch(value) else "unknown"


def _status(value: Any) -> str:
    return value if isinstance(value, str) and value in _STATUSES else "unknown"


def _job_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_code": _code(row.get("job_code")),
        "job_name": str(row.get("job_name") or row.get("job_code") or "未命名")[:100],
        "owner_agent": _code(row.get("owner_agent")),
        "status": _status(row.get("status")),
        "started_at": utc_iso(row.get("started_at")),
        "finished_at": utc_iso(row.get("finished_at")),
        "duration_ms": row.get("duration_ms") if _number(row.get("duration_ms")) else None,
        "retry_count": row.get("retry_count") if _number(row.get("retry_count")) else 0,
    }


def get_execution_overview(conn: Any, limit: int = 100) -> dict[str, Any]:
    """Latest bounded records, not exhaustive current execution/heartbeat truth."""
    agents = [
        {
            "id": row["id"],
            "agent_name": _code(row.get("agent_name")),
            "agent_type": _code(row.get("agent_type")),
            "is_active": bool(row.get("is_active")),
        }
        for row in list_agents(conn)
    ]
    jobs = [_job_metadata(row) for row in list_job_runs(conn, limit=limit)]
    tasks = [
        {
            "id": row["id"],
            "task_code": _code(row.get("task_code")),
            "task_title": str(row.get("task_title") or "未命名")[:100],
            "owner_agent": _code(row.get("owner_agent")),
            "status": _status(row.get("status")),
            "started_at": utc_iso(row.get("started_at")),
            "finished_at": utc_iso(row.get("finished_at")),
            "updated_at": utc_iso(row.get("updated_at")),
            "human_review_required": bool(row.get("human_review_required")),
        }
        for row in list_agent_tasks(conn, limit=50)
    ]
    scheduler = get_scheduler_status()
    return {
        "agents": agents,
        "jobs": jobs,
        "tasks": tasks,
        "scheduler": {
            "running": scheduler.get("running") is True,
            "heartbeat_at": utc_iso(scheduler.get("heartbeat_at")),
        },
        "observed_at": utc_iso(datetime.now(UTC)),
    }


def get_execution_detail(conn: Any, run_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, job_code, job_name, owner_agent, schedule_type, environment,
                      status, retry_count, started_at, finished_at, duration_ms,
                      error_message, input_snapshot_refs, output_refs
               FROM ai_job_runs WHERE id = %s""",
            (run_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    data = dict(
        zip(
            (
                "id",
                "job_code",
                "job_name",
                "owner_agent",
                "schedule_type",
                "environment",
                "status",
                "retry_count",
                "started_at",
                "finished_at",
                "duration_ms",
                "error_message",
                "input_refs",
                "output_refs",
            ),
            row,
            strict=True,
        )
    )
    return {
        **_job_metadata(data),
        "schedule_type": _code(data["schedule_type"]),
        "environment": _code(data["environment"]),
        "has_error": bool(data["error_message"]),
        "error_summary": "执行记录含错误；原始日志仅供服务器审查"
        if data["error_message"]
        else None,
        "input_refs": project_refs(data["input_refs"]),
        "output_refs": project_refs(data["output_refs"]),
        "observed_at": utc_iso(datetime.now(UTC)),
        "upstream_run_ids": None,
        "trace_gap": "未记录明确上游执行 ID；作业代码依赖不证明产物消费或传输",
    }
