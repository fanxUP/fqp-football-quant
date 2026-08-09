"""Fit the over-dispersed score model from official settled results only."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.negative_binomial_model import fit_goal_dispersion

MINIMUM_SETTLED_MATCHES = 100


def _run_with_connection(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT full_home_goals, full_away_goals
            FROM official_results
            WHERE result_status IN ('final', 'confirmed')
              AND full_home_goals IS NOT NULL
              AND full_away_goals IS NOT NULL
            ORDER BY updated_at, id
            """
        )
        rows = cur.fetchall()
    goal_counts = [int(goal) for row in rows for goal in row]
    dispersion = fit_goal_dispersion(goal_counts, minimum_samples=MINIMUM_SETTLED_MATCHES * 2)
    if dispersion is None:
        return {"status": "skipped", "reason": "insufficient_overdispersed_official_results", "sample_count": len(rows)}
    parameters = {
        "rollout_mode": "shadow",
        "converged": True,
        "dispersion": round(dispersion, 8),
        "n_matches": len(rows),
        "evaluation_method": "official_goal_moments_v1",
    }
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE model_versions SET parameters_json=%s
            WHERE model_name='negative_binomial_shadow' AND is_active=true""",
            (Json(parameters),),
        )
        if cur.rowcount != 1:
            raise RuntimeError("negative-binomial shadow model version is not available")
    conn.commit()
    return {"status": "ok", "rollout_mode": "shadow", "training_matches": len(rows), "dispersion": round(dispersion, 6)}


def run(dry_run: bool = False) -> dict[str, Any]:
    """Never promotes the model or changes recommendation and risk decisions."""
    if dry_run:
        return {"status": "dry_run", "message": "negative-binomial shadow training (dry run)"}
    run_id = start_tracked_job(
        "train_negative_binomial_shadow", "model_agent", {"rollout_mode": "shadow"},
        dependencies=["settle_tickets"],
    )
    try:
        with get_db() as conn:
            result = _run_with_connection(conn)
        finish_tracked_job(run_id, result["status"], {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
