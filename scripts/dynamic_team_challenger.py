"""Season-scoped, time-decayed Maher-style team challenger for offline research.

The fitter consumes an already materialized P106 training manifest and an
explicit, evidence-backed season/venue context for each included match. It
never reads a database, carries ratings across seasons, or writes predictions.
"""

from __future__ import annotations

import hashlib
import math
import platform
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from scripts.model_artifact_identity import canonical_json_bytes, training_manifest_sha256
from scripts.poisson_model import derive_1x2, score_matrix
from scripts.training_manifest import MANIFEST_VERSION, SELECTION_VERSION

MODEL_VERSION = "fqp.dynamic-team-poisson/v1"
SEASON_CONTEXT_VERSION = "fqp.dynamic-team-season-context/v1"
SEASON_RESET_POLICY = "neutral_reset_by_competition_season_id/v1"
_OFFICIAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_HASH_FIELDS = (
    "version",
    "selection_version",
    "minimum_team_matches",
    "cutoff_at",
    "training_start",
    "training_end",
    "included",
    "excluded",
)
_IMPLEMENTATION_SOURCE_PATHS = (
    "scripts/dynamic_team_challenger.py",
    "scripts/model_artifact_identity.py",
    "scripts/poisson_model.py",
    "scripts/training_manifest.py",
)


@dataclass(frozen=True)
class DynamicTeamConfig:
    """Versioned and interpretable priors; defaults are not tuned on holdout data."""

    model_version: str = MODEL_VERSION
    half_life_days: int = 120
    base_home_goal_rate_prior: float = 1.45
    base_away_goal_rate_prior: float = 1.15
    baseline_prior_matches: float = 8.0
    team_prior_strength: float = 1.5
    promotion_prior_multiplier: float = 3.0
    home_advantage_prior_log: float = 0.12
    home_advantage_prior_strength: float = 8.0
    mean_constraint_strength: float = 5000.0
    minimum_goal_rate: float = 0.1
    maximum_goal_rate: float = 6.0
    maximum_prediction_age_days: int = 60
    maximum_training_matches: int = 5000
    score_matrix_max_goals_floor: int = 8
    season_transition_policy: str = SEASON_RESET_POLICY

    def __post_init__(self) -> None:
        if self.model_version != MODEL_VERSION:
            raise ValueError("model_version is unsupported")
        if type(self.half_life_days) is not int or not 14 <= self.half_life_days <= 730:
            raise ValueError("half_life_days must be an integer from 14 through 730")
        if (
            type(self.maximum_prediction_age_days) is not int
            or not 1 <= self.maximum_prediction_age_days <= 180
        ):
            raise ValueError("maximum_prediction_age_days must be from 1 through 180")
        if (
            type(self.maximum_training_matches) is not int
            or not 2 <= self.maximum_training_matches <= 5000
        ):
            raise ValueError("maximum_training_matches must be from 2 through 5000")
        if (
            type(self.score_matrix_max_goals_floor) is not int
            or not 5 <= self.score_matrix_max_goals_floor <= 12
        ):
            raise ValueError("score_matrix_max_goals_floor must be from 5 through 12")
        for field_name in (
            "base_home_goal_rate_prior",
            "base_away_goal_rate_prior",
            "baseline_prior_matches",
            "team_prior_strength",
            "promotion_prior_multiplier",
            "home_advantage_prior_strength",
            "mean_constraint_strength",
            "minimum_goal_rate",
            "maximum_goal_rate",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{field_name} must be a finite number")
            if value <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.promotion_prior_multiplier < 1:
            raise ValueError("promotion_prior_multiplier must be at least 1")
        if (
            isinstance(self.home_advantage_prior_log, bool)
            or not isinstance(self.home_advantage_prior_log, (int, float))
            or not math.isfinite(self.home_advantage_prior_log)
            or abs(self.home_advantage_prior_log) > 0.75
        ):
            raise ValueError("home_advantage_prior_log must be finite and within +/-0.75")
        if self.minimum_goal_rate >= self.maximum_goal_rate:
            raise ValueError("minimum_goal_rate must be below maximum_goal_rate")
        if self.season_transition_policy != SEASON_RESET_POLICY:
            raise ValueError("season_transition_policy is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "half_life_days": self.half_life_days,
            "base_home_goal_rate_prior": float(self.base_home_goal_rate_prior),
            "base_away_goal_rate_prior": float(self.base_away_goal_rate_prior),
            "baseline_prior_matches": float(self.baseline_prior_matches),
            "team_prior_strength": float(self.team_prior_strength),
            "promotion_prior_multiplier": float(self.promotion_prior_multiplier),
            "home_advantage_prior_log": float(self.home_advantage_prior_log),
            "home_advantage_prior_strength": float(self.home_advantage_prior_strength),
            "mean_constraint_strength": float(self.mean_constraint_strength),
            "minimum_goal_rate": float(self.minimum_goal_rate),
            "maximum_goal_rate": float(self.maximum_goal_rate),
            "maximum_prediction_age_days": self.maximum_prediction_age_days,
            "maximum_training_matches": self.maximum_training_matches,
            "score_matrix_max_goals_floor": self.score_matrix_max_goals_floor,
            "season_transition_policy": self.season_transition_policy,
            "optimizer": "scipy-lbfgs-b-analytic-gradient/v1",
        }


@dataclass(frozen=True)
class SeasonMatchContext:
    """Canonical competition-season and neutral-venue evidence references for one fixture."""

    competition_id: int
    competition_season_id: int
    neutral_venue: bool
    season_membership_evidence_sha256: str
    season_membership_available_at: datetime | str
    venue_evidence_sha256: str
    venue_evidence_available_at: datetime | str


@dataclass(frozen=True)
class PromotionEvidence:
    """Explicit promotion evidence reference with its point-in-time availability."""

    evidence_ref: str
    available_at: datetime | str


@dataclass(frozen=True)
class DynamicTeamFixture:
    """Prediction-time fixture with caller-resolved, point-in-time identity evidence."""

    match_id: int
    competition_id: int
    competition_season_id: int
    home_team_id: int
    away_team_id: int
    kickoff_at: datetime | str
    prediction_as_of: datetime | str
    neutral_venue: bool
    season_membership_evidence_sha256: str
    season_membership_available_at: datetime | str
    venue_evidence_sha256: str
    venue_evidence_available_at: datetime | str


@dataclass(frozen=True)
class DynamicTeamModel:
    """Immutable fitted candidate state for exactly one competition-season."""

    config: DynamicTeamConfig
    competition_id: int
    competition_season_id: int
    fit_cutoff: datetime
    base_home_goal_rate: float
    base_away_goal_rate: float
    home_advantage_log: float
    attack_log_rate: Mapping[int, float]
    defense_vulnerability_log_rate: Mapping[int, float]
    team_match_counts: Mapping[int, int]
    team_effective_match_counts: Mapping[int, float]
    team_prior_precision: Mapping[int, float]
    promoted_team_evidence: Mapping[int, PromotionEvidence]
    training_sample_weights: Mapping[int, float]
    training_manifest_sha256: str
    season_context_sha256: str
    implementation_identity_sha256: str
    candidate_sha256: str
    optimizer_iterations: int
    optimizer_message: str
    home_advantage_training_matches: int


def _positive_int(value: Any, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _implementation_identity() -> dict[str, Any]:
    """Bind the candidate to its direct model sources and numeric runtime."""
    source_root = Path(__file__).resolve().parents[1]
    source_hashes = {
        relative_path: hashlib.sha256((source_root / relative_path).read_bytes()).hexdigest()
        for relative_path in _IMPLEMENTATION_SOURCE_PATHS
    }
    return {
        "source_sha256_by_path": source_hashes,
        "runtime": {
            "python_implementation": sys.implementation.name,
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "scipy_version": version("scipy"),
        },
    }


def _implementation_identity_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(_implementation_identity())).hexdigest()


def _naive_datetime(value: Any, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if not isinstance(parsed, datetime):
        raise ValueError(f"{field_name} must be an ISO timestamp")
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        raise ValueError(f"{field_name} must use the timezone-naive business-local convention")
    return parsed


def _aware_datetime(value: Any, field_name: str) -> datetime:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an aware ISO timestamp") from exc
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _evidence_digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _season_context(value: Any, match_id: int) -> SeasonMatchContext:
    if isinstance(value, SeasonMatchContext):
        context = value
    elif isinstance(value, Mapping):
        expected = {
            "competition_id",
            "competition_season_id",
            "neutral_venue",
            "season_membership_evidence_sha256",
            "season_membership_available_at",
            "venue_evidence_sha256",
            "venue_evidence_available_at",
        }
        if set(value) != expected:
            raise ValueError(f"season context fields are invalid for match {match_id}")
        context = SeasonMatchContext(**value)
    else:
        raise ValueError(f"season context is missing for match {match_id}")
    _positive_int(context.competition_id, "competition_id")
    _positive_int(context.competition_season_id, "competition_season_id")
    if type(context.neutral_venue) is not bool:
        raise ValueError(f"neutral_venue must be explicit for match {match_id}")
    _evidence_digest(context.season_membership_evidence_sha256, "season membership evidence")
    _evidence_digest(context.venue_evidence_sha256, "venue evidence")
    return context


def _promotion_evidence(
    value: Mapping[int, PromotionEvidence | Mapping[str, Any]] | None,
    *,
    cutoff: datetime,
) -> dict[int, PromotionEvidence]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("promoted_team_evidence must be a mapping")
    result: dict[int, PromotionEvidence] = {}
    for team_id, raw_evidence in value.items():
        team = _positive_int(team_id, "promoted team ID")
        if isinstance(raw_evidence, PromotionEvidence):
            evidence = raw_evidence
        elif isinstance(raw_evidence, Mapping) and set(raw_evidence) == {
            "evidence_ref",
            "available_at",
        }:
            evidence = PromotionEvidence(**raw_evidence)
        else:
            raise ValueError("promotion evidence requires evidence_ref and available_at")
        if (
            not isinstance(evidence.evidence_ref, str)
            or not evidence.evidence_ref.strip()
            or len(evidence.evidence_ref) > 256
        ):
            raise ValueError(
                "promotion evidence reference must be a non-empty string of at most 256 chars"
            )
        available_at = _naive_datetime(evidence.available_at, "promotion evidence available_at")
        if available_at > cutoff:
            raise ValueError("promotion evidence was not available at the fit cutoff")
        result[team] = PromotionEvidence(evidence.evidence_ref.strip(), available_at)
    return result


def _manifest_rows(
    manifest: Mapping[str, Any], cutoff: datetime, max_matches: int
) -> list[dict[str, Any]]:
    if not isinstance(manifest, Mapping):
        raise ValueError("training manifest must be a mapping")
    training_manifest_sha256(manifest)
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("training manifest version is not the P106 Maher-SPF contract")
    if manifest.get("selection_version") != SELECTION_VERSION:
        raise ValueError("training manifest selection policy is not the P106 contract")
    manifest_cutoff = manifest.get("cutoff_at")
    if manifest_cutoff is None:
        raise ValueError("training manifest must have an explicit cutoff")
    if _naive_datetime(manifest_cutoff, "manifest cutoff") != cutoff:
        raise ValueError("fit cutoff must exactly match the P106 manifest cutoff")
    included = manifest.get("included")
    if not isinstance(included, list) or not 2 <= len(included) <= max_matches:
        raise ValueError("training manifest must contain 2 through the configured match limit")
    rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for ordinal, item in enumerate(included):
        if not isinstance(item, Mapping):
            raise ValueError("training manifest contains an invalid sample")
        match_id = _positive_int(item.get("match_id"), "manifest match_id")
        _positive_int(item.get("result_id"), "manifest result_id")
        if item.get("ordinal") != ordinal or type(item.get("ordinal")) is not int:
            raise ValueError("training manifest ordinals must preserve the included sample order")
        if item.get("label_source") != "source_observation:sporttery/results/full_time_score":
            raise ValueError(f"match {match_id} does not use the approved P106 result label")
        if match_id in seen_ids:
            raise ValueError("training manifest contains duplicate match IDs")
        seen_ids.add(match_id)
        home_team_id = _positive_int(item.get("home_team_id"), "home_team_id")
        away_team_id = _positive_int(item.get("away_team_id"), "away_team_id")
        if home_team_id == away_team_id:
            raise ValueError(f"match {match_id} has the same home and away team")
        home_goals, away_goals = item.get("home_goals"), item.get("away_goals")
        if any(type(value) is not int or value < 0 for value in (home_goals, away_goals)):
            raise ValueError(f"match {match_id} has invalid official scores")
        kickoff = _naive_datetime(item.get("kickoff_time"), "kickoff_time")
        published = (
            _naive_datetime(item.get("official_publish_time"), "official_publish_time")
            if item.get("official_publish_time") is not None
            else None
        )
        result_published_at = (
            _aware_datetime(item.get("result_published_at"), "result_published_at")
            if item.get("result_published_at") is not None
            else None
        )
        first_acquired_at = _aware_datetime(
            item.get("result_first_acquired_at"), "result_first_acquired_at"
        )
        available_at = _aware_datetime(item.get("result_available_at"), "result_available_at")
        cutoff_utc = cutoff.replace(tzinfo=_OFFICIAL_TIMEZONE).astimezone(UTC)
        kickoff_utc = kickoff.replace(tzinfo=_OFFICIAL_TIMEZONE).astimezone(UTC)
        source_publication_local = (
            result_published_at.astimezone(_OFFICIAL_TIMEZONE).replace(tzinfo=None)
            if result_published_at is not None
            else None
        )
        if kickoff >= cutoff:
            raise ValueError(f"match {match_id} kicked off at or after the fit cutoff")
        if published is not None and published < kickoff:
            raise ValueError(f"match {match_id} result was published before kickoff")
        if result_published_at is not None and result_published_at < kickoff_utc:
            raise ValueError(f"match {match_id} source label was published before kickoff")
        if (
            published is not None
            and source_publication_local is not None
            and published != source_publication_local
        ):
            raise ValueError(f"match {match_id} publication timestamps disagree")
        if published is not None and published >= cutoff:
            raise ValueError(f"match {match_id} result was published after the fit cutoff")
        if result_published_at is not None and result_published_at >= cutoff_utc:
            raise ValueError(
                f"match {match_id} source label was published at or after the fit cutoff"
            )
        if first_acquired_at >= cutoff_utc:
            raise ValueError(
                f"match {match_id} source label was first acquired at or after the fit cutoff"
            )
        if available_at >= cutoff_utc:
            raise ValueError(
                f"match {match_id} source label was available at or after the fit cutoff"
            )
        if available_at < first_acquired_at or (
            result_published_at is not None and available_at < result_published_at
        ):
            raise ValueError(f"match {match_id} has inconsistent label availability evidence")
        rows.append(
            {
                "match_id": match_id,
                "kickoff": kickoff,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_goals": home_goals,
                "away_goals": away_goals,
            }
        )
    if rows != sorted(rows, key=lambda row: (row["kickoff"], row["match_id"])):
        raise ValueError("training manifest samples must preserve P106 chronological ordering")
    return rows


def _season_context_digest(contexts: Mapping[int, SeasonMatchContext]) -> str:
    payload = {
        "version": SEASON_CONTEXT_VERSION,
        "matches": [
            {
                "match_id": match_id,
                "competition_id": context.competition_id,
                "competition_season_id": context.competition_season_id,
                "neutral_venue": context.neutral_venue,
                "season_membership_evidence_sha256": context.season_membership_evidence_sha256,
                "season_membership_available_at": _naive_datetime(
                    context.season_membership_available_at, "season membership available_at"
                ).isoformat(timespec="microseconds"),
                "venue_evidence_sha256": context.venue_evidence_sha256,
                "venue_evidence_available_at": _naive_datetime(
                    context.venue_evidence_available_at, "venue evidence available_at"
                ).isoformat(timespec="microseconds"),
            }
            for match_id, context in sorted(contexts.items())
        ],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _poisson_cdf_mass(rate: float, through_goals: int) -> float:
    probability = math.exp(-rate)
    mass = probability
    for goals in range(1, through_goals + 1):
        probability *= rate / goals
        mass += probability
    return min(1.0, max(0.0, mass))


def _adaptive_score_matrix_limit(
    lambda_home: float,
    lambda_away: float,
    minimum_max_goals: int,
    *,
    maximum_omitted_mass: float = 1e-10,
    hard_limit: int = 64,
) -> tuple[int, float]:
    """Choose a grid ceiling whose omitted independent-Poisson mass is negligible."""
    maximum_goals = max(minimum_max_goals, math.ceil(max(lambda_home, lambda_away)))
    while maximum_goals <= hard_limit:
        retained_mass = _poisson_cdf_mass(lambda_home, maximum_goals) * _poisson_cdf_mass(
            lambda_away, maximum_goals
        )
        omitted_mass = max(0.0, 1.0 - retained_mass)
        if omitted_mass <= maximum_omitted_mass:
            return maximum_goals, omitted_mass
        maximum_goals += 1
    raise ValueError("score matrix tail exceeds the configured numerical ceiling")


def fit_dynamic_team_challenger(
    training_manifest: Mapping[str, Any],
    season_context_by_match: Mapping[int, SeasonMatchContext | Mapping[str, Any]],
    *,
    config: DynamicTeamConfig | None = None,
    promoted_team_evidence: Mapping[int, PromotionEvidence | Mapping[str, Any]] | None = None,
) -> DynamicTeamModel:
    """Fit one caller-resolved competition-season from the exact P106 manifest.

    Historical results are weighted by their age at the manifest cutoff. No
    rows are reselected or loaded here, and no ratings are inherited from a
    previous season.
    """
    config = config or DynamicTeamConfig()
    if not isinstance(config, DynamicTeamConfig):
        raise TypeError("config must be a DynamicTeamConfig")
    if not isinstance(season_context_by_match, Mapping):
        raise ValueError("season_context_by_match must be a mapping")
    cutoff_value = (
        training_manifest.get("cutoff_at") if isinstance(training_manifest, Mapping) else None
    )
    cutoff = _naive_datetime(cutoff_value, "fit cutoff")
    rows = _manifest_rows(training_manifest, cutoff, config.maximum_training_matches)
    match_ids = {row["match_id"] for row in rows}
    if any(type(match_id) is not int for match_id in season_context_by_match):
        raise ValueError("season context keys must be integer match IDs")
    if set(season_context_by_match) != match_ids:
        raise ValueError("season context keys must exactly match manifest samples")

    contexts = {
        match_id: _season_context(season_context_by_match[match_id], match_id)
        for match_id in sorted(match_ids)
    }
    for match_id, context in contexts.items():
        if (
            _naive_datetime(
                context.season_membership_available_at, "season membership available_at"
            )
            > cutoff
        ):
            raise ValueError(
                f"season membership evidence for match {match_id} was not available at the fit cutoff"
            )
        if (
            _naive_datetime(context.venue_evidence_available_at, "venue evidence available_at")
            > cutoff
        ):
            raise ValueError(
                f"venue evidence for match {match_id} was not available at the fit cutoff"
            )
    season_keys = {
        (context.competition_id, context.competition_season_id) for context in contexts.values()
    }
    if len(season_keys) != 1:
        raise ValueError("a fit must contain one canonical competition-season")
    competition_id, competition_season_id = next(iter(season_keys))
    promotions = _promotion_evidence(promoted_team_evidence, cutoff=cutoff)

    raw_weights = [
        math.exp(
            -math.log(2.0)
            * (cutoff - row["kickoff"]).total_seconds()
            / (config.half_life_days * 86400.0)
        )
        for row in rows
    ]
    mean_weight = math.fsum(raw_weights) / len(raw_weights)
    weights = [weight / mean_weight for weight in raw_weights]
    if any(not math.isfinite(weight) or weight <= 0 for weight in weights):
        raise ValueError("time-decay weights are invalid")
    sample_weights = {
        row["match_id"]: float(weight) for row, weight in zip(rows, weights, strict=True)
    }

    team_ids = sorted(
        {team_id for row in rows for team_id in (row["home_team_id"], row["away_team_id"])}
    )
    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    home_indices = np.asarray([team_index[row["home_team_id"]] for row in rows], dtype=np.int64)
    away_indices = np.asarray([team_index[row["away_team_id"]] for row in rows], dtype=np.int64)
    home_goals = np.asarray([row["home_goals"] for row in rows], dtype=float)
    away_goals = np.asarray([row["away_goals"] for row in rows], dtype=float)
    weight_vector = np.asarray(weights, dtype=float)
    neutral = np.asarray([contexts[row["match_id"]].neutral_venue for row in rows], dtype=bool)
    weighted_total = float(np.sum(weight_vector))
    weighted_goals_per_side = float(
        np.dot(weight_vector, home_goals + away_goals) / (2.0 * weighted_total)
    )
    prior_goals_per_side = (
        config.base_home_goal_rate_prior + config.base_away_goal_rate_prior
    ) / 2.0
    shared_goal_rate = (
        weighted_goals_per_side * weighted_total
        + config.baseline_prior_matches * prior_goals_per_side
    ) / (weighted_total + config.baseline_prior_matches)
    shared_goal_rate = min(
        config.maximum_goal_rate, max(config.minimum_goal_rate, shared_goal_rate)
    )
    # A common league baseline prevents the raw home/away average difference
    # from being counted again by the separately estimated home-advantage term.
    base_home_rate = shared_goal_rate
    base_away_rate = shared_goal_rate
    log_home_base, log_away_base = math.log(base_home_rate), math.log(base_away_rate)
    log_min, log_max = math.log(config.minimum_goal_rate), math.log(config.maximum_goal_rate)
    n_teams = len(team_ids)
    prior_precision = np.asarray(
        [
            config.team_prior_strength
            * (config.promotion_prior_multiplier if team_id in promotions else 1.0)
            for team_id in team_ids
        ],
        dtype=float,
    )

    def objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        attack = parameters[:n_teams]
        defense = parameters[n_teams : 2 * n_teams]
        home_advantage = float(parameters[-1])
        raw_log_home = log_home_base + attack[home_indices] + defense[away_indices]
        raw_log_home = raw_log_home + np.where(neutral, 0.0, home_advantage)
        raw_log_away = log_away_base + attack[away_indices] + defense[home_indices]
        bounded_log_home = np.clip(raw_log_home, log_min, log_max)
        bounded_log_away = np.clip(raw_log_away, log_min, log_max)
        lambda_home = np.exp(bounded_log_home)
        lambda_away = np.exp(bounded_log_away)
        residual_home = weight_vector * (lambda_home - home_goals)
        residual_away = weight_vector * (lambda_away - away_goals)
        residual_home *= (raw_log_home >= log_min) & (raw_log_home <= log_max)
        residual_away *= (raw_log_away >= log_min) & (raw_log_away <= log_max)
        value = float(
            np.sum(weight_vector * (lambda_home - home_goals * bounded_log_home))
            + np.sum(weight_vector * (lambda_away - away_goals * bounded_log_away))
        )
        mean_attack = float(np.mean(attack))
        mean_defense = float(np.mean(defense))
        value += 0.5 * float(np.dot(prior_precision, attack * attack))
        value += 0.5 * float(np.dot(prior_precision, defense * defense))
        value += (
            0.5
            * config.mean_constraint_strength
            * n_teams
            * (mean_attack * mean_attack + mean_defense * mean_defense)
        )
        value += (
            0.5
            * config.home_advantage_prior_strength
            * (home_advantage - config.home_advantage_prior_log) ** 2
        )

        gradient_attack = np.zeros(n_teams, dtype=float)
        gradient_defense = np.zeros(n_teams, dtype=float)
        np.add.at(gradient_attack, home_indices, residual_home)
        np.add.at(gradient_attack, away_indices, residual_away)
        np.add.at(gradient_defense, away_indices, residual_home)
        np.add.at(gradient_defense, home_indices, residual_away)
        gradient_attack += prior_precision * attack
        gradient_defense += prior_precision * defense
        gradient_attack += config.mean_constraint_strength * mean_attack
        gradient_defense += config.mean_constraint_strength * mean_defense
        gradient_home_advantage = float(np.sum(residual_home[~neutral]))
        gradient_home_advantage += config.home_advantage_prior_strength * (
            home_advantage - config.home_advantage_prior_log
        )
        return value, np.concatenate(
            [gradient_attack, gradient_defense, np.asarray([gradient_home_advantage])]
        )

    try:
        from scipy.optimize import minimize
    except ImportError as exc:
        raise RuntimeError(
            "P111 dynamic challenger requires the installed scipy optimizer"
        ) from exc
    initial = np.zeros(2 * n_teams + 1, dtype=float)
    initial[-1] = config.home_advantage_prior_log
    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        jac=True,
        bounds=[(-2.5, 2.5)] * (2 * n_teams) + [(-0.75, 0.75)],
        options={"maxiter": 1000, "ftol": 1e-10, "gtol": 1e-6},
    )
    if not result.success or not np.isfinite(result.fun) or not np.all(np.isfinite(result.x)):
        raise ValueError(f"dynamic team fit did not converge: {result.message}")

    attack_values = {team_id: float(result.x[index]) for index, team_id in enumerate(team_ids)}
    defense_values = {
        team_id: float(result.x[n_teams + index]) for index, team_id in enumerate(team_ids)
    }
    match_counts = {team_id: 0 for team_id in team_ids}
    effective_counts = {team_id: 0.0 for team_id in team_ids}
    for row, weight in zip(rows, weights, strict=True):
        for team_id in (row["home_team_id"], row["away_team_id"]):
            match_counts[team_id] += 1
            effective_counts[team_id] += weight
    prior_by_team = {
        team_id: config.team_prior_strength
        * (config.promotion_prior_multiplier if team_id in promotions else 1.0)
        for team_id in team_ids
    }
    home_advantage_training_matches = int(np.count_nonzero(~neutral))
    season_context_sha = _season_context_digest(contexts)
    manifest_sha = training_manifest_sha256(training_manifest)
    implementation_sha = _implementation_identity_sha256()
    attack_rounded = {str(team_id): round(value, 12) for team_id, value in attack_values.items()}
    defense_rounded = {str(team_id): round(value, 12) for team_id, value in defense_values.items()}
    candidate_payload = {
        "model_version": config.model_version,
        "config": config.to_dict(),
        "competition_id": competition_id,
        "competition_season_id": competition_season_id,
        "fit_cutoff": cutoff.isoformat(timespec="microseconds"),
        "base_home_goal_rate": round(base_home_rate, 12),
        "base_away_goal_rate": round(base_away_rate, 12),
        "home_advantage_log": round(float(result.x[-1]), 12),
        "home_advantage_training_matches": home_advantage_training_matches,
        "attack_log_rate": attack_rounded,
        "defense_vulnerability_log_rate": defense_rounded,
        "team_match_counts": {str(key): value for key, value in sorted(match_counts.items())},
        "team_prior_precision": {str(key): value for key, value in sorted(prior_by_team.items())},
        "promoted_team_evidence": {
            str(key): {
                "evidence_ref": value.evidence_ref,
                "available_at": _naive_datetime(
                    value.available_at, "promotion evidence available_at"
                ).isoformat(timespec="microseconds"),
            }
            for key, value in sorted(promotions.items())
        },
        "training_manifest_sha256": manifest_sha,
        "season_context_sha256": season_context_sha,
        "implementation_identity_sha256": implementation_sha,
    }
    candidate_sha = hashlib.sha256(canonical_json_bytes(candidate_payload)).hexdigest()
    return DynamicTeamModel(
        config=config,
        competition_id=competition_id,
        competition_season_id=competition_season_id,
        fit_cutoff=cutoff,
        base_home_goal_rate=base_home_rate,
        base_away_goal_rate=base_away_rate,
        home_advantage_log=float(result.x[-1]),
        attack_log_rate=attack_values,
        defense_vulnerability_log_rate=defense_values,
        team_match_counts=match_counts,
        team_effective_match_counts=effective_counts,
        team_prior_precision=prior_by_team,
        promoted_team_evidence=promotions,
        training_sample_weights=sample_weights,
        training_manifest_sha256=manifest_sha,
        season_context_sha256=season_context_sha,
        implementation_identity_sha256=implementation_sha,
        candidate_sha256=candidate_sha,
        optimizer_iterations=int(result.nit),
        optimizer_message=str(result.message),
        home_advantage_training_matches=home_advantage_training_matches,
    )


def _team_coverage(model: DynamicTeamModel, team_id: int) -> str:
    count = model.team_match_counts.get(team_id, 0)
    if count == 0:
        return "neutral_prior"
    if team_id in model.promoted_team_evidence:
        return "explicit_promotion_prior_shrunk"
    if count < 5:
        return "small_sample_prior_shrunk"
    return "season_history"


def predict_dynamic_team_challenger(
    model: DynamicTeamModel,
    fixture: DynamicTeamFixture,
) -> dict[str, Any]:
    """Return an offline SPF score matrix and probabilities for one fixture."""
    if not isinstance(model, DynamicTeamModel) or not isinstance(fixture, DynamicTeamFixture):
        raise TypeError("model and fixture must use the dynamic challenger contracts")
    match_id = _positive_int(fixture.match_id, "match_id")
    if fixture.competition_id != model.competition_id or (
        fixture.competition_season_id != model.competition_season_id
    ):
        raise ValueError("fixture competition-season does not match fitted competition-season")
    home_team_id = _positive_int(fixture.home_team_id, "home_team_id")
    away_team_id = _positive_int(fixture.away_team_id, "away_team_id")
    if home_team_id == away_team_id:
        raise ValueError("home and away teams must differ")
    if type(fixture.neutral_venue) is not bool:
        raise ValueError("neutral_venue must be explicit")
    _evidence_digest(fixture.venue_evidence_sha256, "venue evidence")
    _evidence_digest(fixture.season_membership_evidence_sha256, "season membership evidence")
    kickoff = _naive_datetime(fixture.kickoff_at, "kickoff_at")
    as_of = _naive_datetime(fixture.prediction_as_of, "prediction_as_of")
    if as_of >= kickoff:
        raise ValueError("prediction_as_of must be strictly before kickoff")
    if as_of < model.fit_cutoff:
        raise ValueError("prediction_as_of is before the model cutoff")
    if (
        _naive_datetime(fixture.season_membership_available_at, "season membership available_at")
        > as_of
    ):
        raise ValueError("season membership evidence was not available at prediction_as_of")
    if _naive_datetime(fixture.venue_evidence_available_at, "venue evidence available_at") > as_of:
        raise ValueError("venue evidence was not available at prediction_as_of")
    age_days = (as_of - model.fit_cutoff).total_seconds() / 86400.0
    if age_days > model.config.maximum_prediction_age_days:
        raise ValueError("model is stale for the requested prediction_as_of")

    home_attack = model.attack_log_rate.get(home_team_id, 0.0)
    away_attack = model.attack_log_rate.get(away_team_id, 0.0)
    home_defense = model.defense_vulnerability_log_rate.get(home_team_id, 0.0)
    away_defense = model.defense_vulnerability_log_rate.get(away_team_id, 0.0)
    home_advantage = 0.0 if fixture.neutral_venue else model.home_advantage_log
    lambda_home = model.base_home_goal_rate * math.exp(home_attack + away_defense + home_advantage)
    lambda_away = model.base_away_goal_rate * math.exp(away_attack + home_defense)
    lambda_home = min(
        model.config.maximum_goal_rate, max(model.config.minimum_goal_rate, lambda_home)
    )
    lambda_away = min(
        model.config.maximum_goal_rate, max(model.config.minimum_goal_rate, lambda_away)
    )
    matrix_max_goals, omitted_score_tail_mass = _adaptive_score_matrix_limit(
        lambda_home,
        lambda_away,
        minimum_max_goals=model.config.score_matrix_max_goals_floor,
    )
    matrix = score_matrix(lambda_home, lambda_away, max_goals=matrix_max_goals)
    spf = derive_1x2(matrix)
    prediction_context = {
        "version": "fqp.dynamic-team-prediction-context/v1",
        "match_id": match_id,
        "competition_id": model.competition_id,
        "competition_season_id": model.competition_season_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "kickoff_at": kickoff.isoformat(timespec="microseconds"),
        "prediction_as_of": as_of.isoformat(timespec="microseconds"),
        "neutral_venue": fixture.neutral_venue,
        "season_membership_evidence_sha256": fixture.season_membership_evidence_sha256,
        "season_membership_available_at": _naive_datetime(
            fixture.season_membership_available_at, "season membership available_at"
        ).isoformat(timespec="microseconds"),
        "venue_evidence_sha256": fixture.venue_evidence_sha256,
        "venue_evidence_available_at": _naive_datetime(
            fixture.venue_evidence_available_at, "venue evidence available_at"
        ).isoformat(timespec="microseconds"),
    }
    prediction_context_sha = hashlib.sha256(canonical_json_bytes(prediction_context)).hexdigest()
    prediction_sha = hashlib.sha256(
        canonical_json_bytes(
            {
                "candidate_sha256": model.candidate_sha256,
                "prediction_context_sha256": prediction_context_sha,
                "lambda_home": lambda_home,
                "lambda_away": lambda_away,
                "spf_probabilities": spf,
            }
        )
    ).hexdigest()
    return {
        "status": "research_only",
        "model_version": model.config.model_version,
        "match_id": match_id,
        "competition_id": model.competition_id,
        "competition_season_id": model.competition_season_id,
        "prediction_as_of": as_of.isoformat(timespec="microseconds"),
        "kickoff_at": kickoff.isoformat(timespec="microseconds"),
        "model_age_days": round(age_days, 6),
        "neutral_venue": fixture.neutral_venue,
        "season_membership_evidence_sha256": fixture.season_membership_evidence_sha256,
        "venue_evidence_sha256": fixture.venue_evidence_sha256,
        "home_advantage_applied": not fixture.neutral_venue,
        "home_advantage_status": (
            "prior_only_no_non_neutral_training_matches"
            if model.home_advantage_training_matches == 0
            else "estimated_with_versioned_prior"
        ),
        "home_advantage_training_matches": model.home_advantage_training_matches,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "score_matrix_max_goals_used": matrix_max_goals,
        "omitted_score_tail_mass": omitted_score_tail_mass,
        "score_matrix": matrix,
        "spf_probabilities": spf,
        "home_team_match_count": model.team_match_counts.get(home_team_id, 0),
        "away_team_match_count": model.team_match_counts.get(away_team_id, 0),
        "home_team_coverage": _team_coverage(model, home_team_id),
        "away_team_coverage": _team_coverage(model, away_team_id),
        "training_manifest_sha256": model.training_manifest_sha256,
        "season_context_sha256": model.season_context_sha256,
        "implementation_identity_sha256": model.implementation_identity_sha256,
        "candidate_sha256": model.candidate_sha256,
        "prediction_context_sha256": prediction_context_sha,
        "prediction_sha256": prediction_sha,
        "publishable": False,
    }
