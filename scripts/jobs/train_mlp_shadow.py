"""Train MLP as a non-decision shadow signal."""

# ruff: noqa: E701, E702
from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.feature_importance import FEATURE_COLUMNS
from scripts.mlp_shadow_model import fit_temporal_holdout
from scripts.prematch_feature_dataset import load_settled_pre_kickoff_dataset
from scripts.shadow_training import (
    run_tracked_shadow_training,
    train_shadow_with_connection,
)

PROJECT_ROOT, ARTIFACT_RELATIVE_PATH = (
    Path(__file__).resolve().parents[2],
    "var/model_artifacts/mlp_shadow_v1.joblib",
)


def _run_with_connection(conn: Any) -> dict[str, Any]:
    return train_shadow_with_connection(
        conn,
        load_dataset=load_settled_pre_kickoff_dataset,
        fit_model=fit_temporal_holdout,
        feature_columns=FEATURE_COLUMNS,
        resolve_artifact=lambda: PROJECT_ROOT / ARTIFACT_RELATIVE_PATH,
        artifact_relative_path=ARTIFACT_RELATIVE_PATH,
        model_name="mlp_shadow",
        missing_message="MLP shadow model version is not available",
    )


def run(dry_run: bool = False) -> dict[str, Any]:
    return run_tracked_shadow_training(
        dry_run,
        job_name="train_mlp_shadow",
        dry_run_message="MLP shadow training (dry run)",
        run_with_connection=_run_with_connection,
        get_db=get_db,
        start_job=start_tracked_job,
        finish_job=finish_tracked_job,
    )
