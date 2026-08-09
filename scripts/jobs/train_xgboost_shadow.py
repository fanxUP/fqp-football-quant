"""Train the XGBoost pre-match model as a non-decision shadow signal."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.feature_importance import FEATURE_COLUMNS
from scripts.xgboost_shadow_model import fit_temporal_holdout

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_RELATIVE_PATH = "var/model_artifacts/xgboost_shadow_v1.json"


def load_training_dataset(conn: Any) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """Load chronological, official and strictly pre-kickoff feature rows only."""
    columns = ", ".join(f"fs.{column}" for column in FEATURE_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH latest_feature_snapshots AS (
                SELECT DISTINCT ON (fs.match_id) fs.*
                FROM match_feature_snapshots fs
                JOIN official_matches m ON m.id = fs.match_id
                WHERE fs.snapshot_time < m.kickoff_time
                ORDER BY fs.match_id, fs.snapshot_time DESC, fs.id DESC
            )
            SELECT m.kickoff_time, {columns},
                   CASE
                       WHEN r.full_home_goals > r.full_away_goals THEN 2
                       WHEN r.full_home_goals = r.full_away_goals THEN 1
                       ELSE 0
                   END AS label
            FROM latest_feature_snapshots fs
            JOIN official_matches m ON m.id = fs.match_id
            JOIN official_results r ON r.match_id = fs.match_id
            WHERE r.result_status IN ('final', 'confirmed')
            ORDER BY m.kickoff_time ASC, fs.match_id ASC
            LIMIT 5000
            """
        )
        rows = cur.fetchall()
    if not rows:
        return None

    feature_count = len(FEATURE_COLUMNS)
    features = np.array(
        [[float(value) if value is not None else np.nan for value in row[1 : feature_count + 1]] for row in rows],
        dtype=np.float64,
    )
    labels = np.array([int(row[-1]) for row in rows], dtype=np.int64)
    dates = [str(row[0]) for row in rows]
    return features, labels, dates


def _artifact_path() -> Path:
    return PROJECT_ROOT / ARTIFACT_RELATIVE_PATH


def _store_profile(conn: Any, parameters: dict[str, Any], dates: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE model_versions
            SET parameters_json = %s,
                training_start_date = %s,
                training_end_date = %s
            WHERE model_name = 'xgboost_shadow' AND is_active = true
            """,
            (Json(parameters), dates[0][:10], dates[-1][:10]),
        )
        if cur.rowcount != 1:
            raise RuntimeError("xgboost shadow model version is not available")
    conn.commit()


def _run_with_connection(conn: Any) -> dict[str, Any]:
    dataset = load_training_dataset(conn)
    if dataset is None:
        return {"status": "skipped", "reason": "no_settled_pre_match_feature_rows"}
    features, labels, dates = dataset
    try:
        classifier, profile = fit_temporal_holdout(features, labels, tuple(FEATURE_COLUMNS))
    except ValueError as exc:
        return {"status": "skipped", "reason": str(exc), "sample_count": len(labels)}

    artifact_path = _artifact_path()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = artifact_path.with_name(f"{artifact_path.stem}.tmp{artifact_path.suffix}")
    classifier.save_model(str(temporary_path))
    os.replace(temporary_path, artifact_path)

    parameters = {
        "rollout_mode": "shadow",
        "artifact_path": ARTIFACT_RELATIVE_PATH,
        "feature_columns": list(profile.feature_columns),
        "training_matches": profile.training_matches,
        "validation_matches": profile.validation_matches,
        "validation_log_loss": round(profile.validation_log_loss, 8),
        "evaluation_method": "temporal_holdout_v1",
    }
    _store_profile(conn, parameters, dates)
    return {
        "status": "ok",
        "rollout_mode": "shadow",
        "training_matches": profile.training_matches,
        "validation_matches": profile.validation_matches,
        "validation_log_loss": round(profile.validation_log_loss, 6),
    }


def run(dry_run: bool = False) -> dict[str, Any]:
    """Train only after official settlement; never promotes or changes decisions."""
    if dry_run:
        return {"status": "dry_run", "message": "xgboost shadow training (dry run)"}
    run_id = start_tracked_job(
        "train_xgboost_shadow",
        "model_agent",
        {"rollout_mode": "shadow"},
        dependencies=["feature_snapshot_build", "settle_tickets"],
    )
    try:
        with get_db() as conn:
            result = _run_with_connection(conn)
        finish_tracked_job(run_id, result["status"], {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
