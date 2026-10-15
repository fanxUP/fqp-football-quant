"""Train the AdaBoost pre-match model as a non-decision shadow signal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.adaboost_shadow_model import fit_temporal_holdout
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.feature_importance import FEATURE_COLUMNS
from scripts.prematch_feature_dataset import load_settled_pre_kickoff_dataset
from scripts.shadow_training import (
    run_tracked_shadow_training,
    train_shadow_with_connection,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_RELATIVE_PATH = "var/model_artifacts/adaboost_shadow_v1.joblib"


def _run_with_connection(conn: Any) -> dict[str, Any]:
    return train_shadow_with_connection(
        conn,
        load_dataset=load_settled_pre_kickoff_dataset,
        fit_model=fit_temporal_holdout,
        feature_columns=FEATURE_COLUMNS,
        resolve_artifact=lambda: PROJECT_ROOT / ARTIFACT_RELATIVE_PATH,
        artifact_relative_path=ARTIFACT_RELATIVE_PATH,
        model_name="adaboost_shadow",
        missing_message="AdaBoost shadow model version is not available",
    )


def run(dry_run: bool = False) -> dict[str, Any]:
    """Train after settlement; this job cannot promote a decision model."""
    return run_tracked_shadow_training(
        dry_run,
        job_name="train_adaboost_shadow",
        dry_run_message="AdaBoost shadow training (dry run)",
        run_with_connection=_run_with_connection,
        get_db=get_db,
        start_job=start_tracked_job,
        finish_job=finish_tracked_job,
    )
