"""Build an auditable, observation-only player-candidate input receipt."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FEATURES = {
    "home_registered_starters",
    "away_registered_starters",
    "home_reported_unavailable_starters",
    "away_reported_unavailable_starters",
    "home_doubtful_starters",
    "away_doubtful_starters",
}
_COVERAGE_COUNTS = (
    "confirmed_lineup_players",
    "identity_verified_players",
    "registration_known",
)


def _sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("projection timestamp must include a timezone")
    return value.astimezone(UTC)


def _positive_id(value: Any) -> bool:
    return type(value) is int and value > 0


def _valid_ready_projection(projection: dict) -> None:
    if (
        projection.get("schema_version") != "player-feature-projection/v1"
        or projection.get("candidate") != "player_dependent_shadow"
        or projection.get("status") != "candidate_inputs_ready"
    ):
        raise ValueError("unsupported or non-ready player projection")
    if any(
        not _positive_id(projection.get(field))
        for field in ("match_id", "feature_batch_id", "competition_season_id")
    ):
        raise ValueError("player projection identifiers are incomplete")
    cutoff_id = projection.get("observation_cutoff_id")
    if not isinstance(cutoff_id, str) or str(UUID(cutoff_id)) != cutoff_id:
        raise ValueError("player projection cutoff ID is invalid")
    cutoff = _timestamp(projection.get("cutoff_as_of"))
    if not (
        cutoff
        <= _timestamp(projection.get("projected_at"))
        < _timestamp(projection.get("kickoff_at"))
    ):
        raise ValueError("player projection is outside its pre-kickoff cutoff")
    if projection.get("missingness") != []:
        raise ValueError("ready player projection may not contain missing fields")

    identity = projection.get("identity_map_revision")
    refs = projection.get("source_refs")
    if (
        not isinstance(identity, dict)
        or type(identity.get("entry_count")) is not int
        or identity["entry_count"] < 22
        or not isinstance(identity.get("sha256"), str)
        or not _DIGEST.fullmatch(identity["sha256"])
        or not isinstance(refs, dict)
    ):
        raise ValueError("player identity evidence is incomplete")
    identity_rows = refs.get("identity_mapping_revisions")
    registration_ids = refs.get("registration_fact_ids")
    if (
        not isinstance(identity_rows, list)
        or len(identity_rows) != identity["entry_count"]
        or not isinstance(registration_ids, list)
        or len(registration_ids) < 22
        or any(not _positive_id(value) for value in registration_ids)
        or len(set(registration_ids)) != len(registration_ids)
        or _sha256(identity_rows) != identity["sha256"]
    ):
        raise ValueError("identity or registration evidence does not match its summary")
    for row in identity_rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("source_name"), str)
            or not isinstance(row.get("external_player_id"), str)
            or not _positive_id(row.get("player_id"))
            or not _positive_id(row.get("revision"))
            or _timestamp(row.get("updated_at")) > cutoff
        ):
            raise ValueError("identity revision is not valid at the observation cutoff")
    for field in ("lineup_revisions", "availability_revisions"):
        records = refs.get(field)
        if not isinstance(records, dict) or not {"home", "away"} <= records.keys():
            raise ValueError(f"{field} evidence is incomplete")
        for record in records.values():
            if (
                not isinstance(record, dict)
                or not _positive_id(record.get("revision_id"))
                or not isinstance(record.get("content_hash"), str)
                or not _DIGEST.fullmatch(record["content_hash"])
            ):
                raise ValueError(f"{field} evidence is invalid")

    coverage = projection.get("coverage")
    if not isinstance(coverage, dict) or not {"home", "away"} <= coverage.keys():
        raise ValueError("both team coverage records are required")
    for side in ("home", "away"):
        record = coverage[side]
        if (
            not isinstance(record, dict)
            or any(
                type(record.get(field)) is not int or record[field] != 11
                for field in _COVERAGE_COUNTS
            )
            or record.get("availability_report_complete") is not True
        ):
            raise ValueError(f"{side} player coverage is incomplete")

    values = projection.get("feature_values")
    if not isinstance(values, dict) or set(values) != _FEATURES:
        raise ValueError("player feature vector is incomplete")
    if any(type(value) is not int or not 0 <= value <= 11 for value in values.values()):
        raise ValueError("player feature values are invalid")
    if values["home_registered_starters"] != 11 or values["away_registered_starters"] != 11:
        raise ValueError("registered starter coverage is incomplete")
    _sha256(projection)


def _receipt(
    *,
    input_status: str,
    reason: str,
    projection: dict | None = None,
    missingness: list[str] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": "p108-player-candidate-shadow/v1",
        "candidate": "player_dependent_shadow",
        "input_status": input_status,
        "candidate_status": "withheld",
        "rollout_mode": "observation_only",
        "reason": reason,
        "missingness": sorted(set(missingness or [])),
        "feature_projection_sha256": None,
        "probabilities": None,
        "applied_features": [],
    }
    if projection is not None:
        try:
            receipt["feature_projection_sha256"] = _sha256(projection)
        except TypeError, ValueError:
            receipt["feature_projection_sha256"] = None
    return receipt


def build_player_candidate_shadow(projection: dict | None) -> dict[str, Any]:
    """Record player input readiness without inventing an untrained adjustment."""
    if not isinstance(projection, dict):
        return _receipt(
            input_status="withheld",
            reason="player_projection_unavailable",
            missingness=["player_projection_unavailable"],
        )

    if projection.get("status") == "withheld":
        try:
            coverage = projection.get("coverage")
            if (
                projection.get("schema_version") != "player-feature-projection/v1"
                or projection.get("candidate") != "player_dependent_shadow"
                or not isinstance(projection.get("missingness"), list)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in projection["missingness"]
                )
                or projection.get("feature_values") != {}
                or not isinstance(coverage, dict)
                or not {"home", "away"} <= coverage.keys()
            ):
                raise ValueError("invalid withheld projection")
            for side in ("home", "away"):
                record = coverage[side]
                if (
                    not isinstance(record, dict)
                    or any(
                        type(record.get(field)) is not int or not 0 <= record[field] <= 11
                        for field in _COVERAGE_COUNTS
                    )
                    or type(record.get("availability_report_complete")) is not bool
                ):
                    raise ValueError("invalid withheld team coverage")
            _sha256(projection)
        except TypeError, ValueError:
            return _receipt(
                input_status="withheld",
                reason="player_projection_invalid",
                missingness=["projection_invalid"],
            )
        return _receipt(
            input_status="withheld",
            reason="player_inputs_incomplete",
            projection=projection,
            missingness=projection["missingness"],
        )

    try:
        _valid_ready_projection(projection)
    except AttributeError, KeyError, TypeError, ValueError:
        return _receipt(
            input_status="withheld",
            reason="player_projection_invalid",
            missingness=["projection_invalid"],
        )
    return _receipt(
        input_status="ready",
        reason="player_effect_model_not_trained_or_evaluated",
        projection=projection,
    )
