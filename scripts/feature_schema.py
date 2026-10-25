"""Ordered fields of the existing enriched snapshot, shared by readers/writers.

The ordered columns stay fixed; semantic versions prevent a legacy odds proxy
from being consumed as observed form. Old snapshots are never reinterpreted.
"""

from __future__ import annotations

import math
from typing import Any

# Never reorder or reinterpret these fields under the same schema version.
FEATURE_SCHEMA_VERSION = "observed-form/v3"
FEATURE_INPUT_POLICY = "snapshot-columns/v1"
CURRENT_SNAPSHOT_VERSION = "v5_player_facts"
COMPATIBLE_SNAPSHOT_VERSIONS = (CURRENT_SNAPSHOT_VERSION,)
SNAPSHOT_VERSIONS_BY_SCHEMA = {
    "legacy-enriched/v1": ("v1_basic", "v2_enriched", "v3_upset_risk"),
    "observed-form/v2": ("v4_observed_form",),
    FEATURE_SCHEMA_VERSION: COMPATIBLE_SNAPSHOT_VERSIONS,
}


def valid_feature_columns(columns: Any) -> bool:
    """A model may select a unique ordered subset of the known numeric features."""
    return (
        isinstance(columns, (list, tuple))
        and bool(columns)
        and all(isinstance(column, str) and column in FEATURE_COLUMNS for column in columns)
        and len(set(columns)) == len(columns)
    )


def numeric_feature_value(value: Any) -> float:
    """Preserve real zero/false; unavailable or unusable numeric inputs stay missing."""
    try:
        numeric = float(value) if value is not None else math.nan
    except TypeError, ValueError, OverflowError:
        return math.nan
    return numeric if math.isfinite(numeric) else math.nan


FEATURE_COLUMNS: tuple[str, ...] = (
    "home_team_market_value",
    "away_team_market_value",
    "team_market_value_ratio",
    "home_attack_strength_score",
    "away_attack_strength_score",
    "home_defense_strength_score",
    "away_defense_strength_score",
    "home_lineup_confirmed",
    "away_lineup_confirmed",
    "home_starting_11_value",
    "away_starting_11_value",
    "starting_11_value_diff",
    "home_lineup_strength_score",
    "away_lineup_strength_score",
    "lineup_strength_diff",
    "home_absence_impact_score",
    "away_absence_impact_score",
    "absence_impact_diff",
    "home_key_absence_count",
    "away_key_absence_count",
    "home_rotation_risk_score",
    "away_rotation_risk_score",
    "rotation_risk_diff",
    "home_rest_days",
    "away_rest_days",
    "rest_days_diff",
    "away_travel_distance_km",
    "timezone_diff",
    "altitude_m",
    "away_travel_fatigue_score",
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_impact_score",
    "goal_expectation_weather_adjustment",
    "home_motivation_score",
    "away_motivation_score",
    "motivation_diff",
    "home_must_win",
    "away_must_win",
    "home_draw_enough",
    "away_draw_enough",
    "home_avoid_strong_opponent_score",
    "away_avoid_strong_opponent_score",
    "home_tanking_risk_score",
    "away_tanking_risk_score",
    "tournament_incentive_risk_score",
    "upset_risk_score",
    "league_upset_rate",
    "home_team_upset_rate",
    "away_team_upset_rate",
    "upset_risk_confidence",
    "data_completeness_score",
    "source_confidence_score",
    "uncertainty_score",
)

# Extra stored fields are metadata or existing non-model columns, not implicit
# additions to every model's input. Models retain their saved feature subsets.
SNAPSHOT_WRITE_COLUMNS: tuple[str, ...] = (
    "match_id",
    "snapshot_time",
    "feature_version",
    "home_team_id",
    "away_team_id",
    "competition_season_id",
    *FEATURE_COLUMNS,
    "team_market_value_diff",
    "stadium_id",
    "raw_feature_refs",
)
SNAPSHOT_READ_COLUMNS: tuple[str, ...] = ("id", *SNAPSHOT_WRITE_COLUMNS)
