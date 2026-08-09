"""Fit reviewable, shadow-only 1x2 probability calibration profiles."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.business_time import business_now
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
) -> list[dict[str, Any]]:
    """Fit on earlier matches and score profiles on a later temporal holdout."""
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for model_name, match_id, option_code, probability, actual, kickoff_time in rows:
        if option_code not in OUTCOME_CODES or actual not in OUTCOME_CODES:
            continue
        key = (str(model_name), int(match_id))
        entry = grouped.setdefault(
            key,
            {"actual": actual, "kickoff_time": str(kickoff_time), "probabilities": {}},
        )
        if entry["actual"] != actual:
            continue
        entry["probabilities"][option_code] = probability

    samples_by_model: dict[str, list[tuple[str, dict[str, float], str]]] = defaultdict(list)
    for (model_name, _), entry in grouped.items():
        probabilities = entry["probabilities"]
        if set(probabilities) != set(OUTCOME_CODES):
            continue
        try:
            normalized = {code: float(probabilities[code]) for code in OUTCOME_CODES}
        except (TypeError, ValueError):
            continue
        samples_by_model[model_name].append(
            (str(entry["kickoff_time"]), normalized, str(entry["actual"]))
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
    return profiles


def _load_settled_prediction_rows(conn: Any) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_predictions AS (
                SELECT DISTINCT ON (mp.match_id, mv.model_name, mp.play_type, mp.option_code)
                       mp.match_id, mv.model_name, mp.play_type, mp.option_code, mp.model_probability,
                       m.kickoff_time,
                       CASE
                         WHEN r.full_home_goals > r.full_away_goals THEN '3'
                         WHEN r.full_home_goals = r.full_away_goals THEN '1'
                         ELSE '0'
                       END AS actual_result
                FROM model_predictions mp
                JOIN model_versions mv ON mv.id = mp.model_version_id
                JOIN official_matches m ON m.id = mp.match_id
                JOIN official_results r ON r.match_id = mp.match_id
                WHERE mp.play_type = 'spf'
                  AND mp.option_code IN ('3', '1', '0')
                  AND mp.model_probability IS NOT NULL
                  AND mp.predict_time < m.kickoff_time
                  AND mp.validation_status = 'valid'
                ORDER BY mp.match_id, mv.model_name, mp.play_type, mp.option_code,
                         mp.predict_time DESC, mp.id DESC
            )
            SELECT model_name, match_id, option_code, model_probability, actual_result, kickoff_time
            FROM latest_predictions
            ORDER BY model_name, kickoff_time, match_id, option_code
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
    with get_db() as conn:
        rows = _load_settled_prediction_rows(conn)
        profiles = fit_profiles_from_prediction_rows(rows)
        stored = 0 if dry_run else _store_profiles(conn, profiles)
    return {
        "status": "ok",
        "rollout_mode": "shadow",
        "settled_prediction_rows": len(rows),
        "profiles": len(profiles),
        "stored": stored,
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
