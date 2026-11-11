"""Read-only input selection for the explicit observation consumer pilot.

Profiles are trusted internal validation results, not request parameters or an
artifact registry. Readiness never publishes predictions or bypasses the
existing recommendation, release and risk checks.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from scripts.data_contracts import FactStatus, to_utc
from scripts.feature_schema import FEATURE_COLUMNS, valid_feature_columns
from scripts.market_metric_validation import MarketMetricValidationError, validate_market
from scripts.model_signal_policy import MODEL_FAMILIES, supports_market

POLICY_VERSION = "prediction-input-modes/v1"
MAX_PROFILES = 16


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("explicit aware time required")
    return to_utc(value)


@dataclass(frozen=True)
class InputProfile:
    """An explicitly validated ordered input contract for one model version.

    The caller must obtain readiness, independence, rollout and validation from
    controlled model configuration. This declaration does not verify disk
    artifacts or grant publication approval. Missing-pattern validation belongs
    to the same model/preprocessor version named by validation_reference.
    """

    profile_id: str
    model_name: str
    model_version_id: int
    mode: str
    feature_versions: tuple[str, ...]
    feature_columns: tuple[str, ...]
    required_fields: tuple[str, ...]
    validation_reference: str | None = None
    artifact_ready: bool = False
    independent: bool = False
    rollout_mode: str = "shadow"
    validated_missing_patterns: tuple[tuple[str, ...], ...] = ((),)

    def __post_init__(self) -> None:
        if (
            not _text(self.profile_id)
            or not isinstance(self.model_name, str)
            or self.model_name not in MODEL_FAMILIES
            or type(self.model_version_id) is not int
            or self.model_version_id <= 0
            or self.mode not in ("enhanced", "basic")
            or self.rollout_mode not in ("shadow", "live")
            or type(self.artifact_ready) is not bool
            or type(self.independent) is not bool
            or (self.validation_reference is not None and not _text(self.validation_reference))
        ):
            raise ValueError("invalid internal model profile")
        if (
            not isinstance(self.feature_versions, tuple)
            or not 1 <= len(self.feature_versions) <= 8
            or not all(_text(v) for v in self.feature_versions)
            or len(set(self.feature_versions)) != len(self.feature_versions)
            or not isinstance(self.feature_columns, tuple)
            or not valid_feature_columns(self.feature_columns)
            or not isinstance(self.required_fields, tuple)
            or any(not isinstance(f, str) for f in self.required_fields)
            or len(set(self.required_fields)) != len(self.required_fields)
            or not set(self.required_fields) <= set(self.feature_columns)
        ):
            raise ValueError("invalid model feature contract")
        optional = set(self.feature_columns) - set(self.required_fields)
        patterns = self.validated_missing_patterns
        if not isinstance(patterns, tuple) or not 1 <= len(patterns) <= 32:
            raise ValueError("bounded validated missing patterns required")
        seen = set()
        for pattern in patterns:
            if (
                not isinstance(pattern, tuple)
                or any(not isinstance(f, str) for f in pattern)
                or len(set(pattern)) != len(pattern)
                or not set(pattern) <= optional
                or frozenset(pattern) in seen
            ):
                raise ValueError("invalid validated missing pattern")
            seen.add(frozenset(pattern))


@dataclass(frozen=True)
class PredictionContext:
    """One official match/market at a current decision time, supplied internally.

    Open market state and SP references must come from the same authorized
    current read. These caller declarations are not historical identity or
    price-batch proofs; P106 owns persisted run provenance.
    """

    match_id: int
    play_type: str
    decision_at: datetime
    kickoff_at: datetime
    sale_stop_at: datetime | None
    identity_verified: bool
    sale_status: str
    match_status: str
    market_open: bool
    odds_by_option: Mapping[str, Any]
    odds_snapshot_ids: Mapping[str, int]
    handicap: float | None = None

    def __post_init__(self) -> None:
        if (
            type(self.match_id) is not int
            or self.match_id <= 0
            or self.play_type not in ("spf", "rqspf")
            or type(self.identity_verified) is not bool
            or type(self.market_open) is not bool
            or not _text(self.sale_status)
            or not _text(self.match_status)
            or not isinstance(self.odds_by_option, Mapping)
            or not isinstance(self.odds_snapshot_ids, Mapping)
        ):
            raise ValueError("invalid prediction context")
        for name in ("decision_at", "kickoff_at", "sale_stop_at"):
            value = getattr(self, name)
            if name != "sale_stop_at" or value is not None:
                object.__setattr__(self, name, _utc(value))


def _profiles(profiles: Any) -> tuple[InputProfile, ...]:
    if (
        not isinstance(profiles, (list, tuple))
        or len(profiles) > MAX_PROFILES
        or any(not isinstance(p, InputProfile) for p in profiles)
        or len({p.profile_id for p in profiles}) != len(profiles)
    ):
        raise ValueError("bounded profiles with unique IDs required")
    return tuple(profiles)


def _number(value: Any, *, allow_bool: bool = False) -> bool:
    if isinstance(value, bool):
        return allow_bool
    try:
        return isinstance(value, (int, float, Decimal)) and math.isfinite(float(value))
    except OverflowError, ValueError:
        return False


def _handicap(context: PredictionContext) -> float | None:
    if context.handicap is None or not _number(context.handicap):
        return None
    value = float(context.handicap)
    return value if value.is_integer() else None


def _market_available(context: PredictionContext) -> bool:
    odds, refs = context.odds_by_option, context.odds_snapshot_ids
    if (
        set(odds) != {"3", "1", "0"}
        or set(refs) != set(odds)
        or any(not _number(v) or float(v) <= 1 for v in odds.values())
        or any(type(v) is not int or v <= 0 for v in refs.values())
        or (context.play_type == "rqspf" and _handicap(context) is None)
    ):
        return False
    numeric_odds = {k: float(v) for k, v in odds.items()}
    implied = {k: 1 / v for k, v in numeric_odds.items()}
    total = sum(implied.values())
    probabilities = {k: v / total for k, v in implied.items()}
    try:
        validate_market(
            model_probabilities=probabilities,
            market_probabilities=probabilities,
            odds_by_option=numeric_odds,
            snapshot_ids=refs,
        )
    except MarketMetricValidationError:
        return False
    return True


def _input_problem(data: Any, context: PredictionContext) -> str | None:
    if data is None:
        return "no_complete_batch"
    if not isinstance(data, dict):
        return "invalid_input_contract"
    if "match_id" in data and (
        type(data["match_id"]) is not int or data["match_id"] != context.match_id
    ):
        raise ValueError("input belongs to another match")
    if data.get("status") in ("no_complete_batch", "unsupported_batch_contract"):
        return str(data["status"])
    if data.get("status") != "ready" or data.get("match_id") != context.match_id:
        return "invalid_input_contract"
    try:
        at = _utc(datetime.fromisoformat(data["as_of"]))
    except KeyError, TypeError, ValueError, OverflowError:
        return "invalid_input_contract"
    if at != context.decision_at:
        return "input_time_mismatch"
    if at >= context.kickoff_at:
        return "post_kickoff_runtime_unsupported"
    snapshot = data.get("snapshot")
    states, values = data.get("field_statuses"), data.get("values")
    if (
        not isinstance(snapshot, dict)
        or not isinstance(states, dict)
        or set(states) != set(FEATURE_COLUMNS)
        or data.get("feature_columns") != list(FEATURE_COLUMNS)
        or not isinstance(values, list)
        or len(values) != len(FEATURE_COLUMNS)
        or type(data.get("batch_id")) is not int
        or data["batch_id"] <= 0
        or not _text(data.get("cutoff_id"))
        or not _text(snapshot.get("feature_version"))
        or type(snapshot.get("feature_batch_id")) is not int
        or snapshot["feature_batch_id"] != data["batch_id"]
        or snapshot.get("observation_cutoff_id") != data["cutoff_id"]
    ):
        return "invalid_input_contract"
    for name, value in zip(FEATURE_COLUMNS, values, strict=True):
        state = states[name]
        if (
            name not in snapshot
            or type(snapshot[name]) is not type(value)
            or snapshot[name] != value
            or state not in FactStatus
            or (state == "value" and not _number(value, allow_bool=True))
            or (state != "value" and value is not None)
        ):
            return "invalid_input_contract"
    return None


def select_prediction_input_mode(
    *,
    context: PredictionContext,
    feature_input: dict | None,
    profiles: Sequence[InputProfile],
) -> dict:
    """Choose one validated input; all execution eligibility is necessary only.

    Live profiles precede shadow research profiles, then enhanced precedes
    basic, then the controlled caller order breaks ties. This is an operational
    preference, not a claim that an enhanced model predicts better.
    """
    profiles = _profiles(profiles)
    if not isinstance(context, PredictionContext):
        raise ValueError("prediction context required")
    problem = _input_problem(feature_input, context)
    data = feature_input if isinstance(feature_input, dict) else {}
    market_available = _market_available(context)
    excluded, eligible = {}, []
    for profile in profiles:
        reason = problem
        if not reason and not profile.validation_reference:
            reason = "validation_unavailable"
        if not reason and not profile.artifact_ready:
            reason = "artifact_unavailable"
        if not reason and not profile.independent:
            reason = "non_independent_profile"
        if not reason and not supports_market(
            profile.model_name, context.play_type, _handicap(context)
        ):
            reason = "unsupported_market"
        if not reason and data["snapshot"]["feature_version"] not in profile.feature_versions:
            reason = "incompatible_feature_version"
        if not reason:
            missing = {f for f in profile.feature_columns if data["field_statuses"][f] != "value"}
            if missing.intersection(profile.required_fields):
                reason = "missing_required_fields"
            elif len(missing) == len(profile.feature_columns):
                reason = "no_observed_model_fields"
            elif missing not in [set(pattern) for pattern in profile.validated_missing_patterns]:
                reason = "unvalidated_missing_pattern"
        if reason:
            excluded[profile.profile_id] = reason
        else:
            eligible.append(profile)
    eligible.sort(key=lambda p: (p.rollout_mode != "live", p.mode != "enhanced"))
    selected = eligible[0] if eligible else None
    restrictions = []
    if not context.identity_verified:
        restrictions.append("official_identity_unverified")
    if context.sale_status != "selling" or (
        context.sale_stop_at is not None and context.decision_at >= context.sale_stop_at
    ):
        restrictions.append("sale_closed")
    if context.sale_stop_at is None:
        restrictions.append("sale_deadline_unknown")
    if context.match_status.lower() not in ("scheduled", "selling", "not_started"):
        restrictions.append("match_not_scheduled")
    if context.decision_at >= context.kickoff_at:
        restrictions.append("kickoff_reached")
    if not context.market_open:
        restrictions.append("market_closed")
    if not market_available:
        restrictions.append("invalid_official_market")
    if selected is None:
        restrictions.append("no_qualified_independent_input")
    elif selected.rollout_mode != "live":
        restrictions.append("shadow_only")
    return dict(
        policy_version=POLICY_VERSION,
        match_id=context.match_id,
        play_type=context.play_type,
        as_of=context.decision_at.isoformat(),
        mode=selected.mode
        if selected
        else "market_reference"
        if market_available
        else "awaiting_verification",
        profile_id=selected.profile_id if selected else None,
        model_name=selected.model_name if selected else None,
        model_version_id=selected.model_version_id if selected else None,
        validation_reference=selected.validation_reference if selected else None,
        model_independent=selected is not None,
        recommendation_eligible=not restrictions,
        restrictions=restrictions,
        market_reference_available=market_available,
        feature_batch_id=data["batch_id"] if not problem else None,
        observation_cutoff_id=data["cutoff_id"] if not problem else None,
        feature_version=data["snapshot"]["feature_version"] if not problem else None,
        field_statuses=dict(data["field_statuses"]) if not problem else {},
        feature_columns=list(selected.feature_columns) if selected else [],
        values=[data["snapshot"][f] for f in selected.feature_columns] if selected else [],
        missing_fields=[f for f in selected.feature_columns if data["field_statuses"][f] != "value"]
        if selected
        else [],
        eligible_profile_ids=[p.profile_id for p in eligible],
        excluded_profiles=excluded,
    )


def load_prediction_input_mode(
    conn: Any,
    *,
    batch_id: int,
    context: PredictionContext,
    profiles: Sequence[InputProfile],
) -> dict:
    """Read the exact P104 batch once; no commits, latest reads or source calls."""
    from scripts.observed_feature_pipeline import load_observed_feature_input

    profiles = _profiles(profiles)
    if not isinstance(context, PredictionContext):
        raise ValueError("prediction context required")
    if type(batch_id) is not int or batch_id <= 0:
        raise ValueError("positive batch ID required")
    data = None
    if profiles and context.decision_at < context.kickoff_at:
        data = load_observed_feature_input(
            conn,
            batch_id=batch_id,
            match_id=context.match_id,
            as_of=context.decision_at,
            feature_columns=FEATURE_COLUMNS,
            required_fields=(),
        )
    return select_prediction_input_mode(context=context, feature_input=data, profiles=profiles)
