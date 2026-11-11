"""Explicit local consumer pilot; no default scheduler or artifact activation.

Full field coverage means every input is explained. It does not mean enough
signals exist for a model. Caller-declared team/kickoff context is retained,
not presented as a historical identity mapping or fixture observation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from scripts.data_catalog import get_field_resolution_policy
from scripts.data_contracts import to_utc
from scripts.feature_batch_storage import MAX_BATCH_BYTES, load_feature_batch, store_feature_batch
from scripts.feature_schema import FEATURE_COLUMNS, valid_feature_columns
from scripts.observation_resolution import resolve_observed_field
from scripts.observation_storage import ObservationCutoff, _canonical, load_observation_selection

BUILDER_VERSION = "observed-cutoff-pilot/v1"
DERIVATION_VERSION = "observed-input/v1"
_UNAVAILABLE = dict(
    version=DERIVATION_VERSION, kind="unavailable", reason="no_point_in_time_derivation"
)
_RULES = ("weather.temperature_2m", "lineup.starters", "injuries.complete_report")
_DECISION_FIELDS = (
    ("temperature_2m", "weather.temperature_2m", "forecast"),
    ("home_lineup_confirmed", "lineup.starters", "home"),
    ("away_lineup_confirmed", "lineup.starters", "away"),
    ("home_key_absence_count", "injuries.complete_report", "home"),
    ("away_key_absence_count", "injuries.complete_report", "away"),
)


def _time(value: Any) -> datetime:
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("aware time required")
        return to_utc(at)
    except ValueError, TypeError, OverflowError:
        raise ValueError("explicit aware time required") from None


def validate_context(context: Any) -> dict:
    """Canonical explicit caller declaration; never infer IDs from current aliases."""
    if not isinstance(context, dict) or set(context) != {
        "home_team_id",
        "away_team_id",
        "kickoff_at",
    }:
        raise ValueError("context requires explicit teams and kickoff")
    if (
        any(
            type(context[k]) is not int or context[k] <= 0 for k in ("home_team_id", "away_team_id")
        )
        or context["home_team_id"] == context["away_team_id"]
    ):
        raise ValueError("context requires distinct canonical teams")
    try:
        at = _time(context["kickoff_at"])
    except ValueError:
        raise ValueError("context requires aware kickoff time") from None
    return dict(context, kickoff_at=at.isoformat())


def _features(
    conn: Any, *, match_id: int, cutoff: ObservationCutoff, context: dict, policies: dict
) -> dict:
    context = validate_context(context)
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("canonical match required")
    if not isinstance(cutoff, ObservationCutoff) or cutoff.include_reconstruction:
        raise ValueError("runtime cutoff required")
    if _time(cutoff.as_of) >= _time(context["kickoff_at"]):
        raise ValueError("cutoff time must precede declared kickoff")
    if set(policies) != set(_RULES):
        raise ValueError("all pilot policies required")
    selections = load_observation_selection(conn, cutoff)
    if any(item["match_id"] != match_id for item in selections):
        raise ValueError("cutoff must contain only this match")
    features: dict[str, dict[str, Any]] = {
        field: dict(
            fact_status="unknown",
            value=None,
            observation_indexes=[],
            derivation=deepcopy(_UNAVAILABLE),
        )
        for field in FEATURE_COLUMNS
    }
    for name, field, side in _DECISION_FIELDS:
        subject = "forecast" if side == "forecast" else f"team:{context[side + '_team_id']}"
        decision = resolve_observed_field(
            conn,
            match_id=match_id,
            cutoff=cutoff,
            field=field,
            subject_key=subject,
            policy=policies[field],
        )
        status, value = decision["fact_status"], decision["value"]
        kind, reason = "resolved", "field_policy"
        if field == "injuries.complete_report":
            # A report (including confirmed empty) says nothing about key status
            # or impact without a separately validated player contribution model.
            status, value, kind, reason = "unknown", None, "unavailable", "no_key_player_derivation"
        elif field == "lineup.starters" and status == "value":
            value = True  # Exact canonical eleven only; no eligibility inference.
        elif field == "weather.temperature_2m" and status == "value":
            targets = {
                c["effective_at"]
                for c in decision["candidates"]
                if c["index"] in decision["selected_indexes"]
            }
            if targets != {context["kickoff_at"]}:
                status, value, reason = "unknown", None, "forecast_target_mismatch"
        refs = (
            decision["selected_indexes"]
            if status == "value"
            else [c["index"] for c in decision["candidates"]]
        )
        features[name] = dict(
            fact_status=status,
            value=value,
            observation_indexes=refs,
            derivation=dict(
                version=DERIVATION_VERSION,
                kind=kind,
                reason=reason,
                context=deepcopy(context),
                resolution=decision,
            ),
        )
    return features


def build_observed_feature_batch(
    conn: Any, *, match_id: int, cutoff: ObservationCutoff, context: dict
) -> int:
    """Build and insert all 55 fields together; caller owns commit/rollback.

    The caller captures declared sources separately, before any batch writes.
    No source calls, identity lookups, latest projections or hidden commits.
    """
    policies = {field: get_field_resolution_policy(field) for field in _RULES}
    features = _features(conn, match_id=match_id, cutoff=cutoff, context=context, policies=policies)
    return store_feature_batch(
        conn,
        match_id=match_id,
        cutoff=cutoff,
        builder_version=BUILDER_VERSION,
        required_fields=FEATURE_COLUMNS,
        features=features,
    )


def load_observed_feature_input(
    conn: Any,
    *,
    batch_id: int,
    match_id: int,
    as_of: datetime,
    feature_columns: Any,
    required_fields: Any,
) -> dict:
    """Read/recompute exact pilot ID with the retained policy; never use latest.

    Readiness is for the explicitly declared input requirement only. The unique
    feature_version deliberately fails existing artifact compatibility guards.
    It does not authorize a trained artifact or claim a P106 run manifest.
    """
    if (
        not valid_feature_columns(feature_columns)
        or not isinstance(required_fields, (tuple, list))
        or any(not isinstance(f, str) for f in required_fields)
        or len(set(required_fields)) != len(required_fields)
        or not set(required_fields) <= set(feature_columns)
    ):
        raise ValueError("invalid model columns/required columns")
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("canonical match required")
    at = _time(as_of)
    result: dict[str, Any] = dict(
        batch_id=batch_id,
        match_id=match_id,
        cutoff_id=None,
        feature_columns=list(feature_columns),
        values=[None] * len(feature_columns),
        missing_required_fields=list(required_fields),
        field_statuses={},
        snapshot=None,
        as_of=at.isoformat(),
    )
    batch = load_feature_batch(conn, batch_id)
    if batch is None:
        return dict(result, status="no_complete_batch")
    if batch["match_id"] != match_id:
        raise ValueError("batch belongs to another match")
    if batch["builder_version"] != BUILDER_VERSION or batch["required_fields"] != list(
        FEATURE_COLUMNS
    ):
        return dict(result, status="unsupported_batch_contract")
    fields = batch["features"]
    try:
        context = fields["temperature_2m"]["derivation"]["context"]
        policies: dict[str, dict] = {}
        for name, field, _ in _DECISION_FIELDS:
            policy = fields[name]["derivation"]["resolution"]["policy"]
            if field in policies and policy != policies[field]:
                raise ValueError("inconsistent pilot policies")
            policies[field] = policy
        replayed = _features(
            conn, match_id=match_id, cutoff=batch["cutoff"], context=context, policies=policies
        )
    except KeyError, TypeError:
        raise ValueError("missing pilot derivation context/policy") from None
    if _canonical(replayed, MAX_BATCH_BYTES) != _canonical(fields, MAX_BATCH_BYTES):
        raise ValueError("batch does not match named observation derivation")
    if not batch["cutoff"].as_of <= at < _time(context["kickoff_at"]):
        raise ValueError("prediction time must follow cutoff and precede kickoff")
    values = {}
    statuses = {}
    for name, field in fields.items():
        status, value = field["fact_status"], field["value"]
        if status == "value":
            decision = field["derivation"]["resolution"]
            selected = [
                c for c in decision["candidates"] if c["index"] in decision["selected_indexes"]
            ]
            if not selected or any(at >= _time(c["expires_at"]) for c in selected):
                status, value = "stale", None
        values[name], statuses[name] = value, status
    missing = [f for f in required_fields if statuses[f] != "value"]
    snapshot = dict(
        values,
        feature_version=BUILDER_VERSION,
        feature_batch_id=batch_id,
        observation_cutoff_id=batch["cutoff_id"],
        home_team_id=context["home_team_id"],
        away_team_id=context["away_team_id"],
    )
    return dict(
        result,
        status="insufficient_inputs" if missing else "ready",
        cutoff_id=batch["cutoff_id"],
        values=[values[f] for f in feature_columns],
        field_statuses=statuses,
        missing_required_fields=missing,
        snapshot=None if missing else snapshot,
    )
