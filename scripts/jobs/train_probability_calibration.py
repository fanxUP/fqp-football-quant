"""Fit reviewable, shadow-only 1x2 probability calibration profiles."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.business_time import business_now
from scripts.market_metric_validation import spf_probability_vector
from scripts.model_evaluation_scope import CALIBRATION_PREDICTIONS_CTE
from scripts.probability_calibration import (
    OUTCOME_CODES,
    evaluate_temperature_scaling_temporal_holdout,
)

MINIMUM_CALIBRATION_SAMPLES = 100
MINIMUM_VALIDATION_SAMPLES = 25


def fit_profiles_from_prediction_rows(
    rows: list[tuple[Any, ...]],
    minimum_samples: int = MINIMUM_CALIBRATION_SAMPLES,
    minimum_validation_samples: int = MINIMUM_VALIDATION_SAMPLES,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fit on earlier matches and score profiles on a later temporal holdout."""
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for model_name, match_id, option_code, probability, actual, kickoff_time in rows:
        key = (str(model_name), int(match_id))
        entry = grouped.setdefault(
            key,
            {
                "actual": actual,
                "kickoff_time": str(kickoff_time),
                "probabilities": {},
                "invalid": False,
            },
        )
        if (
            option_code not in OUTCOME_CODES
            or actual not in OUTCOME_CODES
            or entry["actual"] != actual
            or entry["kickoff_time"] != str(kickoff_time)
            or option_code in entry["probabilities"]
        ):
            entry["invalid"] = True
            continue
        entry["probabilities"][option_code] = probability

    samples_by_model: dict[str, list[tuple[str, dict[str, float], str]]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    for (model_name, _), entry in grouped.items():
        probabilities = entry["probabilities"]
        validated = spf_probability_vector(probabilities)
        if entry["invalid"] or validated is None:
            rejected[model_name] += 1
            continue
        samples_by_model[model_name].append(
            (str(entry["kickoff_time"]), validated, str(entry["actual"]))
        )

    profiles: list[dict[str, Any]] = []
    for model_name, samples in sorted(samples_by_model.items()):
        chronological_samples = [
            (probabilities, actual)
            for _, probabilities, actual in sorted(samples, key=lambda sample: sample[0])
        ]
        profile = evaluate_temperature_scaling_temporal_holdout(
            chronological_samples,
            minimum_training_samples=minimum_samples,
            minimum_validation_samples=minimum_validation_samples,
        )
        if profile is not None:
            profiles.append({"model_name": model_name, "play_type": "spf", **profile})
    if diagnostics is not None:
        diagnostics.update(
            {
                "candidate_groups": len(grouped),
                "valid_groups": sum(map(len, samples_by_model.values())),
                "rejected_groups": sum(rejected.values()),
                "rejected_by_model": dict(sorted(rejected.items())),
            }
        )
    return profiles


def _load_settled_prediction_rows(conn: Any) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            {CALIBRATION_PREDICTIONS_CTE}
            SELECT canonical_model_name, match_id, option_code, model_probability,
                   actual_result, kickoff_time
            FROM calibration_predictions
            ORDER BY canonical_model_name, kickoff_time, match_id, option_code
            """
        )
        return list(cur.fetchall())


def _store_profiles(conn: Any, profiles: list[dict[str, Any]]) -> int:
    if not profiles:
        return 0
    fitted_at = business_now()
    training_end_date = fitted_at.date().isoformat()
    calibration_version = f"temperature-{fitted_at.strftime('%Y%m%dT%H%M%S')}"
    with conn.cursor() as cur:
        for profile in profiles:
            cur.execute(
                """
                UPDATE probability_calibration_profiles
                SET is_active = false
                WHERE model_name = %s AND play_type = %s AND is_active = true
                """,
                (profile["model_name"], profile["play_type"]),
            )
            cur.execute(
                """
                INSERT INTO probability_calibration_profiles (
                    model_name, play_type, method_name, calibration_version,
                    parameters_json, sample_count, log_loss_before, log_loss_after,
                    is_active, training_end_date
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, true, %s)
                """,
                (
                    profile["model_name"],
                    profile["play_type"],
                    profile["method_name"],
                    calibration_version,
                    json.dumps(
                        {
                            "temperature": profile["temperature"],
                            "training_sample_count": profile["training_sample_count"],
                            "validation_sample_count": profile["validation_sample_count"],
                            "evaluation_method": "temporal_holdout",
                        }
                    ),
                    profile["sample_count"],
                    profile["log_loss_before"],
                    profile["log_loss_after"],
                    training_end_date,
                ),
            )
    conn.commit()
    return len(profiles)


def _run_impl(dry_run: bool = False) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    with get_db() as conn:
        rows = _load_settled_prediction_rows(conn)
        profiles = fit_profiles_from_prediction_rows(rows, diagnostics=diagnostics)
        stored = 0 if dry_run else _store_profiles(conn, profiles)
    return {
        "status": "ok",
        "rollout_mode": "shadow",
        "settled_prediction_rows": len(rows),
        "profiles": len(profiles),
        "stored": stored,
        "sample_quality": diagnostics,
        "note": "校准结果仅供评估，不会写回预测、推荐或风控链路",
    }


def run(dry_run: bool = False) -> dict[str, Any]:
    """Run the calibration fit under the tracked model-agent job boundary."""
    run_id = start_tracked_job(
        "train_probability_calibration",
        "model_agent",
        {"dry_run": dry_run, "rollout_mode": "shadow"},
        dependencies=[] if dry_run else ["compute_evaluation_metrics"],
    )
    try:
        result = _run_impl(dry_run=dry_run)
        finish_tracked_job(run_id, result["status"], {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
