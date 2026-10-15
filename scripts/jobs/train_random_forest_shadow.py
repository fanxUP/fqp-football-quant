"""Train the random-forest pre-match model as a non-decision shadow signal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.feature_importance import FEATURE_COLUMNS
from scripts.prematch_feature_dataset import load_settled_pre_kickoff_dataset
from scripts.random_forest_shadow_model import fit_temporal_holdout
from scripts.shadow_training import (
    run_tracked_shadow_training,
    store_active_shadow_profile,
    train_shadow_with_connection,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_RELATIVE_PATH = "var/model_artifacts/random_forest_shadow_v1.joblib"
load_training_dataset = load_settled_pre_kickoff_dataset


def _artifact_path() -> Path:
    return PROJECT_ROOT / ARTIFACT_RELATIVE_PATH


def _store_profile(conn: Any, parameters: dict[str, Any], dates: list[str]) -> None:
    store_active_shadow_profile(
        conn,
        parameters,
        dates,
        model_name="random_forest_shadow",
        missing_message="random forest shadow model version is not available",
    )


def _run_with_connection(conn: Any) -> dict[str, Any]:
    return train_shadow_with_connection(
        conn,
        load_dataset=load_training_dataset,
        fit_model=fit_temporal_holdout,
        feature_columns=FEATURE_COLUMNS,
        resolve_artifact=_artifact_path,
        artifact_relative_path=ARTIFACT_RELATIVE_PATH,
        model_name="random_forest_shadow",
        missing_message="random forest shadow model version is not available",
        store_profile=_store_profile,
    )


def run(dry_run: bool = False) -> dict[str, Any]:
    """Train after settlement; this job cannot promote a decision model."""
    return run_tracked_shadow_training(
        dry_run,
        job_name="train_random_forest_shadow",
        dry_run_message="random forest shadow training (dry run)",
        run_with_connection=_run_with_connection,
        get_db=get_db,
        start_job=start_tracked_job,
        finish_job=finish_tracked_job,
    )
