"""Shared orchestration for the existing pre-match shadow-training jobs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from psycopg2.extras import Json


def store_active_shadow_profile(
    conn: Any,
    parameters: dict[str, Any],
    dates: list[str],
    *,
    model_name: str,
    missing_message: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE model_versions
            SET parameters_json = %s, training_start_date = %s, training_end_date = %s
            WHERE model_name = %s AND is_active = true
            """,
            (Json(parameters), dates[0][:10], dates[-1][:10], model_name),
        )
        if cur.rowcount != 1:
            raise RuntimeError(missing_message)
    conn.commit()


def train_shadow_with_connection(
    conn: Any,
    *,
    load_dataset: Callable[[Any], Any],
    fit_model: Callable[..., Any],
    feature_columns: Any,
    resolve_artifact: Callable[[], Path],
    artifact_relative_path: str,
    model_name: str,
    missing_message: str,
    store_profile: Callable[..., None] | None = None,
    save_artifact: Callable[[Any, Path], Any] | None = None,
) -> dict[str, Any]:
    dataset = load_dataset(conn)
    if dataset is None:
        return {"status": "skipped", "reason": "no_settled_pre_match_feature_rows"}
    features, labels, dates = dataset
    try:
        classifier, profile = fit_model(features, labels, tuple(feature_columns))
    except ValueError as exc:
        return {"status": "skipped", "reason": str(exc), "sample_count": len(labels)}

    if save_artifact is None:
        import joblib

        save_artifact = joblib.dump

    artifact_path = resolve_artifact()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = artifact_path.with_name(f"{artifact_path.stem}.tmp{artifact_path.suffix}")
    save_artifact(classifier, temporary_path)
    os.replace(temporary_path, artifact_path)
    parameters = {
        "rollout_mode": "shadow",
        "artifact_path": artifact_relative_path,
        "feature_columns": list(profile.feature_columns),
        "training_matches": profile.training_matches,
        "validation_matches": profile.validation_matches,
        "validation_log_loss": round(profile.validation_log_loss, 8),
        "evaluation_method": "temporal_holdout_v1",
    }
    if store_profile is None:
        store_active_shadow_profile(
            conn,
            parameters,
            dates,
            model_name=model_name,
            missing_message=missing_message,
        )
    else:
        store_profile(conn, parameters, dates)
    return {
        "status": "ok",
        "rollout_mode": "shadow",
        "training_matches": profile.training_matches,
        "validation_matches": profile.validation_matches,
        "validation_log_loss": round(profile.validation_log_loss, 6),
    }


def run_tracked_shadow_training(
    dry_run: bool,
    *,
    job_name: str,
    dry_run_message: str,
    run_with_connection: Callable[[Any], dict[str, Any]],
    get_db: Callable[..., Any],
    start_job: Callable[..., Any],
    finish_job: Callable[..., Any],
) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run", "message": dry_run_message}
    run_id = start_job(
        job_name,
        "model_agent",
        {"rollout_mode": "shadow"},
        dependencies=["feature_snapshot_build", "settle_tickets"],
    )
    try:
        with get_db() as conn:
            result = run_with_connection(conn)
        finish_job(run_id, result["status"], {"result": result})
        return result
    except Exception as exc:
        finish_job(run_id, "failed", error=str(exc))
        raise
