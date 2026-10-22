"""One-model SPF shadow output built only from an exact P104 observation batch."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from scripts.features.build_weather_features import (
    compute_temperature_goal_expectation_adjustment,
)
from scripts.maher_goal_rate_runtime import load_trained_goal_rates
from scripts.observed_feature_pipeline import BUILDER_VERSION
from scripts.poisson_model import derive_1x2, score_matrix

CALCULATION_VERSION = "observed_maher_spf_shadow/v1"
TEMPERATURE_RULE_VERSION = "weather-temperature-only/v1"
_AUDIT_FIELDS = (
    "temperature_2m",
    "home_lineup_confirmed",
    "away_lineup_confirmed",
    "home_key_absence_count",
    "away_key_absence_count",
)


def _revision_ids(batch: dict, fields: tuple[str, ...]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    feature_map = batch.get("features", {})
    if not isinstance(feature_map, dict):
        return result
    for name in fields:
        feature = feature_map.get(name, {})
        if not isinstance(feature, dict):
            continue
        indexes = feature.get("observation_indexes", [])
        derivation = feature.get("derivation", {})
        resolution = derivation.get("resolution", {}) if isinstance(derivation, dict) else {}
        if not isinstance(indexes, list) or not isinstance(resolution, dict):
            continue
        candidates = resolution.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        by_index = {item.get("index"): item for item in candidates if isinstance(item, dict)}
        refs = sorted(
            {
                by_index[index]["revision_id"]
                for index in indexes
                if index in by_index
                and type(by_index[index].get("revision_id")) is int
                and by_index[index]["revision_id"] > 0
            }
        )
        if refs:
            result[name] = refs
    return result


def build_observed_maher_shadow(
    *,
    model_version_id: int | None,
    model_parameters: dict[str, Any] | None,
    feature_input: dict,
    batch: dict,
    input_version: int,
    as_of: Any,
) -> dict:
    """Compute a non-publishable SPF shadow result or an explicit unavailable ref."""
    match_id = batch.get("match_id")
    cutoff_id = batch.get("cutoff_id")
    batch_id = batch.get("id")
    base = {
        "schema_version": 1,
        "calculation_version": CALCULATION_VERSION,
        "match_id": match_id,
        "input_version": input_version,
        "feature_batch_id": batch_id,
        "observation_cutoff_id": cutoff_id,
        "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
        "play_type": "spf",
        "rollout_mode": "shadow",
        "model_name": "maher_poisson",
        "model_version_id": model_version_id,
        "feature_statuses": {
            name: feature_input.get("field_statuses", {}).get(name) for name in _AUDIT_FIELDS
        },
        "feature_values": {
            name: feature_input.get("snapshot", {}).get(name) for name in _AUDIT_FIELDS
        },
        "source_revision_ids": _revision_ids(batch, _AUDIT_FIELDS),
        "not_applied_features": [
            {"feature": name, "reason": "player_contribution_mapping_unavailable"}
            for name in (
                "home_lineup_confirmed",
                "away_lineup_confirmed",
                "home_key_absence_count",
                "away_key_absence_count",
            )
        ],
        "probabilities": None,
        "applied_features": [],
        "adjustment": None,
    }
    try:
        valid_cutoff_id = isinstance(cutoff_id, str) and str(UUID(cutoff_id)) == cutoff_id
    except TypeError, ValueError:
        valid_cutoff_id = False
    if (
        type(match_id) is not int
        or match_id <= 0
        or type(batch_id) is not int
        or batch_id <= 0
        or not valid_cutoff_id
        or type(input_version) is not int
        or input_version <= 0
    ):
        return dict(base, status="observed_input_unavailable", reason="invalid_exact_batch_ids")

    snapshot = feature_input.get("snapshot") or {}
    features = batch.get("features") or {}
    temperature_feature = features.get("temperature_2m", {}) if isinstance(features, dict) else {}
    temperature_derivation = (
        temperature_feature.get("derivation", {}) if isinstance(temperature_feature, dict) else {}
    )
    temperature_context = (
        temperature_derivation.get("context", {})
        if isinstance(temperature_derivation, dict)
        else {}
    )
    if (
        batch.get("builder_version") != BUILDER_VERSION
        or not isinstance(snapshot, dict)
        or snapshot.get("feature_version") != BUILDER_VERSION
        or snapshot.get("feature_batch_id") != batch_id
        or snapshot.get("observation_cutoff_id") != cutoff_id
        or not isinstance(temperature_context, dict)
        or snapshot.get("home_team_id") != temperature_context.get("home_team_id")
        or snapshot.get("away_team_id") != temperature_context.get("away_team_id")
        or feature_input.get("status") != "ready"
        or feature_input.get("match_id") != match_id
        or feature_input.get("batch_id") != batch_id
        or feature_input.get("cutoff_id") != cutoff_id
        or feature_input.get("feature_columns") != list(_AUDIT_FIELDS)
    ):
        return dict(base, status="observed_input_unavailable", reason="exact_batch_not_ready")
    if (
        type(model_version_id) is not int
        or model_version_id <= 0
        or not isinstance(model_parameters, dict)
    ):
        return dict(base, status="model_unavailable", reason="no_active_maher_version")

    team_snapshot = {
        "home_team_id": snapshot.get("home_team_id"),
        "away_team_id": snapshot.get("away_team_id"),
    }
    rates = load_trained_goal_rates({"maher_poisson": model_parameters}, team_snapshot)
    if rates is None:
        return dict(base, status="model_unavailable", reason="active_maher_parameters_not_usable")
    if feature_input.get("field_statuses", {}).get("temperature_2m") != "value":
        return dict(base, status="observation_unavailable", reason="temperature_not_observed")

    temperature = snapshot.get("temperature_2m")
    try:
        weather_adjustment = compute_temperature_goal_expectation_adjustment(temperature)
    except ValueError:
        return dict(base, status="observation_unavailable", reason="temperature_invalid")
    weather_impact = round(-weather_adjustment * 1000.0, 4)
    multiplier = max(0.88, min(1.05, 1.0 + weather_adjustment))
    adjusted_home = rates.home_lambda * multiplier
    adjusted_away = rates.away_lambda * multiplier
    probabilities = derive_1x2(score_matrix(adjusted_home, adjusted_away))
    if (
        set(probabilities) != {"3", "1", "0"}
        or not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in probabilities.values())
        or abs(sum(probabilities.values()) - 1.0) > 1e-9
    ):
        return dict(base, status="calculation_invalid", reason="probability_invariant_failed")
    adjustment = {
        "feature": "temperature_2m",
        "rule_version": TEMPERATURE_RULE_VERSION,
        "observed_celsius": float(temperature),
        "temperature_impact_score": weather_impact,
        "goal_expectation_adjustment": weather_adjustment,
        "goal_rate_multiplier": round(multiplier, 6),
        "home_lambda_before": round(rates.home_lambda, 6),
        "away_lambda_before": round(rates.away_lambda, 6),
        "home_lambda_after": round(adjusted_home, 6),
        "away_lambda_after": round(adjusted_away, 6),
    }
    return dict(
        base,
        status="computed_shadow",
        reason=None,
        applied_features=["temperature_2m"],
        training_matches=rates.training_matches,
        minimum_team_matches=rates.minimum_team_matches,
        probabilities={key: round(value, 10) for key, value in probabilities.items()},
        adjustment=adjustment,
    )
