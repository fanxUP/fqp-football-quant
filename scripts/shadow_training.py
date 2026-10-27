"""Shared orchestration for the existing pre-match shadow-training jobs."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg2.extras import Json

from scripts.feature_schema import (
    FEATURE_INPUT_POLICY,
    FEATURE_SCHEMA_VERSION,
    valid_feature_columns,
)
from scripts.shadow_model_helpers import artifact_matches_features, load_shadow_artifact


def store_active_shadow_profile(
    conn: Any,
    parameters: dict[str, Any],
    dates: list[str],
    *,
    model_name: str,
    missing_message: str,
) -> None:
    """Own this connection's transaction: insert a new version, never mutate old metadata."""
    if conn.autocommit is True:
        raise ValueError("shadow activation requires autocommit=False")
    try:
        with conn.cursor() as cur:
            # Every shadow trainer uses this common switch; concurrent training may
            # save files independently, but activation for one model is serialized.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"fqp:shadow-profile:{model_name}",),
            )
            cur.execute(
                "SELECT id FROM model_versions WHERE model_name=%s AND is_active=true FOR UPDATE",
                (model_name,),
            )
            rows = cur.fetchall()
            if len(rows) != 1:
                raise RuntimeError(missing_message)
            previous_id = rows[0][0]
            cur.execute("UPDATE model_versions SET is_active=false WHERE id=%s", (previous_id,))
            cur.execute(
                """INSERT INTO model_versions (
                       model_name, model_type, version, paper_key,
                       training_start_date, training_end_date,
                       training_window_start, training_window_end,
                       feature_set_version, parameters_json, description, is_active)
                   SELECT model_name, model_type, %s, paper_key, %s, %s, %s, %s,
                          %s, %s, description, true
                   FROM model_versions WHERE id=%s""",
                (
                    parameters["artifact_version"],
                    dates[0][:10],
                    dates[-1][:10],
                    dates[0][:10],
                    dates[-1][:10],
                    parameters["feature_schema_version"],
                    Json(parameters),
                    previous_id,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError(missing_message)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


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
    artifact_format: str = "joblib",
) -> dict[str, Any]:
    if getattr(conn, "autocommit", False) is True:
        raise ValueError("shadow training requires autocommit=False")
    if not valid_feature_columns(feature_columns):
        raise ValueError("feature columns must be a known unique ordered subset")
    dataset = load_dataset(conn)
    if dataset is None:
        return {"status": "skipped", "reason": "no_settled_pre_match_feature_rows"}
    features, labels, dates = dataset
    if features.ndim != 2 or features.shape[1] != len(feature_columns):
        raise ValueError("feature matrix width must match declared feature columns")
    try:
        classifier, profile = fit_model(features, labels, tuple(feature_columns))
    except ValueError as exc:
        return {"status": "skipped", "reason": str(exc), "sample_count": len(labels)}

    if tuple(profile.feature_columns) != tuple(feature_columns) or not artifact_matches_features(
        classifier, tuple(feature_columns)
    ):
        raise ValueError("fitted artifact feature contract does not match training input")

    if save_artifact is None:
        import joblib

        save_artifact = joblib.dump

    base_path = resolve_artifact()
    base_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_version = f"shadow-{uuid4().hex}"
    filename = f"{base_path.stem}.{artifact_version}{base_path.suffix}"
    artifact_path = base_path.with_name(filename)
    relative_path = Path(artifact_relative_path).with_name(filename).as_posix()
    fd, temporary = tempfile.mkstemp(
        dir=base_path.parent, prefix=f".{artifact_version}.tmp", suffix=base_path.suffix
    )
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        save_artifact(classifier, temporary_path)
        content = temporary_path.read_bytes()
        artifact_metadata = {
            "artifact_sha256": hashlib.sha256(content).hexdigest(),
            "artifact_size_bytes": len(content),
        }
        restored = load_shadow_artifact(
            str(temporary_path), artifact_metadata, artifact_format=artifact_format
        )
        if not artifact_matches_features(restored, tuple(feature_columns)):
            raise ValueError("saved artifact feature contract does not match training input")
        with temporary_path.open("rb") as saved_file:
            os.fsync(saved_file.fileno())
        temporary_path.chmod(0o444)
        # link is atomic and fails if the destination exists, unlike replace.
        os.link(temporary_path, artifact_path)
        temporary_path.unlink()
        directory_fd = os.open(base_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)
    parameters = {
        "rollout_mode": "shadow",
        "artifact_path": relative_path,
        "artifact_version": artifact_version,
        **artifact_metadata,
        "feature_columns": list(profile.feature_columns),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_input_policy": FEATURE_INPUT_POLICY,
        "training_matches": profile.training_matches,
        "validation_matches": profile.validation_matches,
        "validation_log_loss": round(profile.validation_log_loss, 8),
        "evaluation_method": "temporal_holdout_v1",
    }
    try:
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
    except BaseException:
        # The published file may be unreferenced after failure. Keep it for
        # reconciliation: a lost COMMIT acknowledgement is not proof of rollback.
        if store_profile is not None:
            conn.rollback()
        raise
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
