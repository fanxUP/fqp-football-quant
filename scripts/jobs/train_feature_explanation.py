"""Train the existing analysis-only model outside HTTP requests."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.feature_importance import train_if_needed


def run(dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run", "scope": "explanation_only"}
    run_id = start_tracked_job(
        "train_feature_explanation", "model_agent", {"scope": "explanation_only"}
    )
    if run_id is None:
        raise RuntimeError("explanation training requires an audit run ID")
    try:
        with get_db() as conn:
            result = train_if_needed(conn, force=True)
        if result.get("reason") in {
            "insufficient_data",
            "missing_features",
            "insufficient_classes",
        }:
            result = {**result, "status": "skipped"}
        finish_tracked_job(
            run_id,
            "failed" if result["status"] == "error" else result["status"],
            {"result": result},
            error=result.get("error") if result["status"] == "error" else None,
        )
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
