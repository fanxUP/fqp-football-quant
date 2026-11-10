"""P106 run/evaluation adapter for the inactive P111 dynamic-team challenger.

This adapter is for isolated research runs. Completed groups are stored through
the existing P106 tables; callers must not invoke it against production because
those tables are also read by some general prediction views.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

from scripts.dynamic_team_challenger import (
    DynamicTeamConfig,
    DynamicTeamFixture,
    DynamicTeamModel,
    PromotionEvidence,
    SeasonMatchContext,
    fit_dynamic_team_challenger,
    predict_dynamic_team_challenger,
)
from scripts.model_artifact_identity import canonical_json_bytes, training_manifest_sha256
from scripts.model_prediction_run_identity import (
    build_model_artifact_identity,
    content_sha256,
    fingerprint_runtime_sources,
)
from scripts.model_prediction_run_storage import (
    create_prediction_run,
    fail_prediction_run,
    finalize_prediction_run,
    store_prediction_group,
)
from scripts.model_storage import safe_fair_odds
from scripts.model_training_manifest_storage import (
    load_training_manifest,
    persist_training_manifest,
)
from scripts.odds_conversion import normalize_probabilities
from scripts.training_manifest import MANIFEST_VERSION, SELECTION_VERSION

MODEL_NAME = "dynamic_team_poisson_shadow"
MODEL_TYPE = "dynamic_team_poisson"
FEATURE_SET_VERSION = "p111-dynamic-team-season-context/v1"
CALCULATION_VERSION = "p111_p106_shadow_v1"
PROJECTION_VERSION = "p111-p106-single-season-projection/v1"
_OPTIONS = ("0", "1", "3")
_OFFICIAL_OPTION_TO_CANONICAL = {
    "0": "0",
    "1": "1",
    "3": "3",
    "a": "0",
    "d": "1",
    "h": "3",
}
_ISOLATED_DATABASE_COMMENT = "fqp-p111-p106-isolated-fixtures/v1"
_ODDS_MAX_AGE_SECONDS = 45 * 60
_OFFICIAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_RUNTIME_SOURCE_PATHS = (
    "scripts/dynamic_team_p106.py",
    "scripts/dynamic_team_challenger.py",
    "scripts/model_artifact_identity.py",
    "scripts/model_prediction_run_identity.py",
    "scripts/model_prediction_run_storage.py",
    "scripts/model_storage.py",
    "scripts/model_training_manifest_storage.py",
    "scripts/odds_conversion.py",
    "scripts/poisson_model.py",
    "scripts/training_manifest.py",
    "scripts/backtest_engine.py",
    "scripts/evaluation_metrics.py",
)


@dataclass(frozen=True)
class P106SeasonProjection:
    """Auditable single-season projection of one exact P106 parent manifest."""

    manifest: dict[str, Any]
    parent_training_manifest_sha256: str
    competition_id: int
    competition_season_id: int
    season_context_sha256: str
    projection_sha256: str
    included_match_ids: tuple[int, ...]
    excluded_match_ids: tuple[int, ...]
    audit: tuple[dict[str, Any], ...]
    selected_contexts: dict[int, SeasonMatchContext]


@dataclass(frozen=True)
class _LoadedMarket:
    odds: dict[str, float]
    odds_text: dict[str, str]
    snapshot_ids: dict[str, int]
    snapshot_times: dict[str, datetime]
    snapshot_created_at: dict[str, datetime]


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_isolated_research_database(conn: Any) -> None:
    """Require a loopback DSN and trusted server-side marker for the test database."""
    getter = getattr(conn, "get_dsn_parameters", None)
    if not callable(getter):
        raise TypeError("P111 shadow integration requires a psycopg2 connection")
    parameters = getter()
    if not callable(getattr(conn, "get_transaction_status", None)):
        raise TypeError("P111 shadow integration requires a psycopg2 connection")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("P111 shadow integration requires an idle connection")
    if getattr(conn, "autocommit", False) is True:
        raise ValueError("P111 shadow integration requires autocommit disabled")

    def one_loopback_address(value: Any) -> bool:
        addresses = [part.strip().strip("[]").lower() for part in str(value or "").split(",")]
        return len(addresses) == 1 and addresses[0] in {"localhost", "127.0.0.1", "::1"}

    host = parameters.get("host")
    hostaddr = parameters.get("hostaddr")
    database = str(parameters.get("dbname") or "")
    if (
        (host and not one_loopback_address(host))
        or (hostaddr and not one_loopback_address(hostaddr))
        or not (host or hostaddr)
        or not database.startswith("fqp_p106_test_")
    ):
        raise ValueError(
            "P111 shadow integration is restricted to loopback fqp_p106_test_* databases"
        )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT pg_catalog.current_database(),
                          pg_catalog.shobj_description(d.oid, 'pg_database')
                   FROM pg_catalog.pg_database AS d
                   WHERE d.datname=pg_catalog.current_database()"""
            )
            server_database, database_comment = cursor.fetchone()
    finally:
        # This read-only attestation must not leave a transaction for callers.
        conn.rollback()
    if server_database != database or database_comment != _ISOLATED_DATABASE_COMMENT:
        raise ValueError("P111 shadow integration database attestation did not match")


def _naive_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field} must be an ISO datetime")
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        raise ValueError(f"{field} must be timezone-naive")
    return parsed


def _datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _p106_timestamp_text(value: Any, field: str) -> str:
    """Match P106's timestamp JSON representation (omit zero microseconds)."""
    return _naive_datetime(value, field).isoformat()


def _validate_parent_manifest(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], datetime, list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(manifest, Mapping):
        raise ValueError("parent P106 manifest must be a mapping")
    parent = dict(manifest)
    training_manifest_sha256(parent)
    if parent.get("version") != MANIFEST_VERSION:
        raise ValueError("parent manifest is not the P106 Maher-SPF contract")
    if parent.get("selection_version") != SELECTION_VERSION:
        raise ValueError("parent manifest does not use the P106 selection policy")
    cutoff_value = parent.get("cutoff_at")
    if cutoff_value is None:
        raise ValueError("parent P106 manifest requires an explicit cutoff")
    cutoff = _naive_datetime(cutoff_value, "parent fit cutoff")
    if type(parent.get("minimum_team_matches")) is not int or parent["minimum_team_matches"] < 1:
        raise ValueError("parent P106 minimum_team_matches is invalid")
    included = parent.get("included")
    excluded = parent.get("excluded")
    if not isinstance(included, list) or not isinstance(excluded, list):
        raise ValueError("parent manifest included/excluded rows must be arrays")

    seen: set[int] = set()
    checked_included: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(included):
        if not isinstance(raw, Mapping):
            raise ValueError("parent manifest contains an invalid included sample")
        row = dict(raw)
        match_id = _positive_int(row.get("match_id"), "parent match_id")
        if match_id in seen:
            raise ValueError("parent manifest repeats a match ID")
        seen.add(match_id)
        if row.get("ordinal") != ordinal or type(row.get("ordinal")) is not int:
            raise ValueError("parent manifest ordinals must be contiguous and ordered")
        _positive_int(row.get("result_id"), "parent result_id")
        if row.get("label_source") != "official_results.full_home_goals/full_away_goals":
            raise ValueError(f"parent match {match_id} uses an unsupported result label")
        home_id = _positive_int(row.get("home_team_id"), "parent home_team_id")
        away_id = _positive_int(row.get("away_team_id"), "parent away_team_id")
        if home_id == away_id:
            raise ValueError(f"parent match {match_id} has identical team IDs")
        if any(
            type(row.get(name)) is not int or row[name] < 0 for name in ("home_goals", "away_goals")
        ):
            raise ValueError(f"parent match {match_id} has an invalid official score")
        kickoff = _naive_datetime(row.get("kickoff_time"), "parent kickoff_time")
        published = _naive_datetime(
            row.get("official_publish_time"), "parent official_publish_time"
        )
        if kickoff >= cutoff or published < kickoff or published > cutoff:
            raise ValueError(f"parent match {match_id} violates the P106 cutoff")
        checked_included.append(row)
    ordered = sorted(
        checked_included,
        key=lambda row: (_naive_datetime(row["kickoff_time"], "kickoff_time"), row["match_id"]),
    )
    if checked_included != ordered:
        raise ValueError("parent included samples are not in P106 chronological order")

    checked_excluded: list[dict[str, Any]] = []
    for raw in excluded:
        if not isinstance(raw, Mapping):
            raise ValueError("parent manifest contains an invalid excluded sample")
        row = dict(raw)
        match_id = _positive_int(row.get("match_id"), "excluded match_id")
        if match_id in seen:
            raise ValueError("parent included/excluded samples repeat a match ID")
        seen.add(match_id)
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError(f"parent excluded match {match_id} has no exclusion reason")
        checked_excluded.append(row)

    expected_start = checked_included[0]["kickoff_time"] if checked_included else None
    expected_end = checked_included[-1]["kickoff_time"] if checked_included else None
    if parent.get("training_start") != expected_start or parent.get("training_end") != expected_end:
        raise ValueError("parent manifest training range does not match its included rows")
    return parent, cutoff, checked_included, checked_excluded


def _normalize_context(value: Any, match_id: int) -> tuple[SeasonMatchContext, dict[str, Any]]:
    fields = {
        "competition_id",
        "competition_season_id",
        "neutral_venue",
        "season_membership_evidence_sha256",
        "season_membership_available_at",
        "venue_evidence_sha256",
        "venue_evidence_available_at",
    }
    if isinstance(value, SeasonMatchContext):
        raw = asdict(value)
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise ValueError(f"season context for match {match_id} is invalid")
    if set(raw) != fields:
        raise ValueError(f"season context for match {match_id} has an unsupported shape")
    competition_id = _positive_int(raw["competition_id"], "context competition_id")
    season_id = _positive_int(raw["competition_season_id"], "context competition_season_id")
    if type(raw["neutral_venue"]) is not bool:
        raise ValueError(f"season context for match {match_id} requires explicit neutral_venue")
    for name in ("season_membership_evidence_sha256", "venue_evidence_sha256"):
        digest = raw[name]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"season context for match {match_id} has an invalid {name}")
    membership_at = _naive_datetime(
        raw["season_membership_available_at"], "season membership available_at"
    )
    venue_at = _naive_datetime(raw["venue_evidence_available_at"], "venue available_at")
    context = SeasonMatchContext(
        competition_id=competition_id,
        competition_season_id=season_id,
        neutral_venue=raw["neutral_venue"],
        season_membership_evidence_sha256=raw["season_membership_evidence_sha256"],
        season_membership_available_at=membership_at,
        venue_evidence_sha256=raw["venue_evidence_sha256"],
        venue_evidence_available_at=venue_at,
    )
    normalized = {
        "competition_id": competition_id,
        "competition_season_id": season_id,
        "neutral_venue": raw["neutral_venue"],
        "season_membership_evidence_sha256": raw["season_membership_evidence_sha256"],
        "season_membership_available_at": _datetime_text(membership_at),
        "venue_evidence_sha256": raw["venue_evidence_sha256"],
        "venue_evidence_available_at": _datetime_text(venue_at),
    }
    return context, normalized


def project_p106_manifest_to_season(
    parent_manifest: Mapping[str, Any],
    season_context_by_match: Mapping[int, SeasonMatchContext | Mapping[str, Any] | None],
    *,
    competition_id: int,
    competition_season_id: int,
) -> P106SeasonProjection:
    """Project exactly one P106 manifest into one evidence-backed season.

    Every parent included match is either kept or appended to the derived
    manifest's excluded list with a P111 reason. Existing P106 labels and
    exclusions are preserved; this function never reselects or relabels a row.
    """
    competition_id = _positive_int(competition_id, "competition_id")
    competition_season_id = _positive_int(competition_season_id, "competition_season_id")
    parent, cutoff, included, original_excluded = _validate_parent_manifest(parent_manifest)
    if not isinstance(season_context_by_match, Mapping):
        raise ValueError("season context input must be a mapping")
    if any(type(match_id) is not int for match_id in season_context_by_match):
        raise ValueError("season context keys must be integer match IDs")
    parent_ids = {row["match_id"] for row in included}
    if set(season_context_by_match) != parent_ids:
        raise ValueError("season context keys must exactly match parent included samples")

    normalized_contexts: dict[str, Any] = {}
    contexts: dict[int, SeasonMatchContext | None] = {}
    for match_id in sorted(parent_ids):
        raw = season_context_by_match[match_id]
        if raw is None:
            contexts[match_id] = None
            normalized_contexts[str(match_id)] = None
        else:
            context, normalized = _normalize_context(raw, match_id)
            contexts[match_id] = context
            normalized_contexts[str(match_id)] = normalized
    context_digest_payload = {
        "version": "p111-parent-season-context/v1",
        "parent_training_manifest_sha256": parent["sha256"],
        "context_by_match": normalized_contexts,
    }
    season_context_sha = content_sha256(context_digest_payload)

    derived_included: list[dict[str, Any]] = []
    derived_excluded = [dict(row) for row in original_excluded]
    audit: list[dict[str, Any]] = []
    selected_contexts: dict[int, SeasonMatchContext] = {}
    p111_excluded: list[int] = []
    for row in included:
        match_id = row["match_id"]
        match_context = contexts[match_id]
        reason: str | None = None
        if match_context is None:
            reason = "p111_context_missing"
        elif (
            _naive_datetime(
                match_context.season_membership_available_at, "season membership available_at"
            )
            > cutoff
            or _naive_datetime(match_context.venue_evidence_available_at, "venue available_at")
            > cutoff
        ):
            reason = "p111_context_after_fit_cutoff"
        elif (
            match_context.competition_id != competition_id
            or match_context.competition_season_id != competition_season_id
        ):
            reason = "p111_other_competition_season"
        if reason is None:
            assert match_context is not None
            sample = dict(row)
            sample["ordinal"] = len(derived_included)
            derived_included.append(sample)
            selected_contexts[match_id] = match_context
        else:
            p111_excluded.append(match_id)
            derived_excluded.append(
                {
                    "match_id": match_id,
                    "result_id": row["result_id"],
                    "kickoff_time": row["kickoff_time"],
                    "official_publish_time": row["official_publish_time"],
                    "home_team_id": row["home_team_id"],
                    "away_team_id": row["away_team_id"],
                    "home_goals": row["home_goals"],
                    "away_goals": row["away_goals"],
                    "match_status": "settled",
                    "reason": reason,
                }
            )
        audit.append(
            {
                "match_id": match_id,
                "included": reason is None,
                "reason": reason,
                "context": normalized_contexts[str(match_id)],
            }
        )

    derived_excluded.sort(
        key=lambda row: (
            str(row.get("kickoff_time") or ""),
            int(row["match_id"]),
            str(row["reason"]),
        )
    )
    hash_payload = {
        "version": parent["version"],
        "selection_version": parent["selection_version"],
        "minimum_team_matches": parent["minimum_team_matches"],
        "cutoff_at": parent["cutoff_at"],
        "training_start": derived_included[0]["kickoff_time"] if derived_included else None,
        "training_end": derived_included[-1]["kickoff_time"] if derived_included else None,
        "included": derived_included,
        "excluded": derived_excluded,
    }
    derived_manifest = {
        **hash_payload,
        "sha256": hashlib.sha256(canonical_json_bytes(hash_payload)).hexdigest(),
    }
    training_manifest_sha256(derived_manifest)
    projection_payload = {
        "version": PROJECTION_VERSION,
        "parent_training_manifest_sha256": parent["sha256"],
        "derived_training_manifest_sha256": derived_manifest["sha256"],
        "competition_id": competition_id,
        "competition_season_id": competition_season_id,
        "season_context_sha256": season_context_sha,
        "audit": audit,
    }
    projection_sha = content_sha256(projection_payload)
    return P106SeasonProjection(
        manifest=derived_manifest,
        parent_training_manifest_sha256=parent["sha256"],
        competition_id=competition_id,
        competition_season_id=competition_season_id,
        season_context_sha256=season_context_sha,
        projection_sha256=projection_sha,
        included_match_ids=tuple(row["match_id"] for row in derived_included),
        excluded_match_ids=tuple(p111_excluded),
        audit=tuple(audit),
        selected_contexts=selected_contexts,
    )


def _model_artifact_parameters(
    model: DynamicTeamModel,
    projection: P106SeasonProjection,
) -> dict[str, Any]:
    parameters = {
        "schema_version": "p111.dynamic-team-poisson-artifact/v1",
        "rollout_mode": "shadow",
        "publishable": False,
        "candidate_sha256": model.candidate_sha256,
        "model_version": model.config.model_version,
        "config": model.config.to_dict(),
        "competition_id": model.competition_id,
        "competition_season_id": model.competition_season_id,
        "fit_cutoff": _datetime_text(model.fit_cutoff),
        "parent_training_manifest_sha256": projection.parent_training_manifest_sha256,
        "training_manifest_sha256": model.training_manifest_sha256,
        "projection_sha256": projection.projection_sha256,
        "season_context_sha256": model.season_context_sha256,
        "projection_context_sha256": projection.season_context_sha256,
        "implementation_identity_sha256": model.implementation_identity_sha256,
        "base_home_goal_rate": model.base_home_goal_rate,
        "base_away_goal_rate": model.base_away_goal_rate,
        "home_advantage_log": model.home_advantage_log,
        "home_advantage_training_matches": model.home_advantage_training_matches,
        "attack_log_rate": {
            str(key): value for key, value in sorted(model.attack_log_rate.items())
        },
        "defense_vulnerability_log_rate": {
            str(key): value for key, value in sorted(model.defense_vulnerability_log_rate.items())
        },
        "team_match_counts": {
            str(key): value for key, value in sorted(model.team_match_counts.items())
        },
        "team_effective_match_counts": {
            str(key): value for key, value in sorted(model.team_effective_match_counts.items())
        },
        "team_prior_precision": {
            str(key): value for key, value in sorted(model.team_prior_precision.items())
        },
        "promoted_team_evidence": {
            str(key): {
                "evidence_ref": value.evidence_ref,
                "available_at": _datetime_text(
                    _naive_datetime(value.available_at, "promotion available_at")
                ),
            }
            for key, value in sorted(model.promoted_team_evidence.items())
        },
        "training_sample_weights": {
            str(key): value for key, value in sorted(model.training_sample_weights.items())
        },
        "optimizer_iterations": model.optimizer_iterations,
        "optimizer_message": model.optimizer_message,
        "rollout_policy": "inactive_model_version_only;no_scheduler_or_committee",
    }
    parameters["artifact_sha256"] = content_sha256(parameters)
    return parameters


def _manifest_date(value: str | None) -> date | None:
    if value is None:
        return None
    return _naive_datetime(value, "training range").date()


def _persist_inactive_model(
    conn: Any,
    *,
    parameters: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> int:
    if getattr(conn, "autocommit", False) is True:
        raise ValueError("P111 shadow persistence requires autocommit=False")
    artifact_parameters = dict(parameters)
    artifact_sha = artifact_parameters.pop("artifact_sha256", None)
    if not isinstance(artifact_sha, str) or artifact_sha != content_sha256(artifact_parameters):
        raise ValueError("P111 model version requires a digest of its complete immutable artifact")
    version = artifact_sha
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_versions (
                       model_name, model_type, version, training_start_date,
                       training_end_date, training_window_start, training_window_end,
                       feature_set_version, parameters_json, description, is_active
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false)
                   ON CONFLICT (model_name, version) DO NOTHING
                   RETURNING id""",
                (
                    MODEL_NAME,
                    MODEL_TYPE,
                    version,
                    _manifest_date(manifest.get("training_start")),
                    _manifest_date(manifest.get("training_end")),
                    _manifest_date(manifest.get("training_start")),
                    _manifest_date(manifest.get("training_end")),
                    FEATURE_SET_VERSION,
                    Json(dict(parameters)),
                    "P111 season-aware dynamic team candidate; research-only inactive shadow.",
                ),
            )
            inserted = cursor.fetchone()
            if inserted is not None:
                model_version_id = int(inserted[0])
                persist_training_manifest(conn, model_version_id, manifest)
            else:
                cursor.execute(
                    """SELECT id, is_active, parameters_json
                       FROM model_versions WHERE model_name=%s AND version=%s FOR UPDATE""",
                    (MODEL_NAME, version),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("shadow candidate version disappeared after conflict")
                model_version_id = int(existing[0])
                if existing[1] is not False:
                    raise ValueError("existing P111 candidate version is not inactive")
                stored_parameters = existing[2]
                if isinstance(stored_parameters, str):
                    import json

                    stored_parameters = json.loads(stored_parameters)
                if not isinstance(stored_parameters, Mapping) or canonical_json_bytes(
                    dict(stored_parameters)
                ) != canonical_json_bytes(dict(parameters)):
                    raise ValueError("existing P111 candidate version has different parameters")
                stored_manifest = load_training_manifest(conn, model_version_id)
                if stored_manifest is None or stored_manifest != dict(manifest):
                    raise ValueError("existing P111 candidate has no matching immutable manifest")
        conn.commit()
        return model_version_id
    except Exception:
        conn.rollback()
        raise


def _validate_fixture_set(
    target_fixtures: Sequence[DynamicTeamFixture],
    market_snapshot_ids_by_match: Mapping[int, Mapping[str, int]],
) -> tuple[list[DynamicTeamFixture], dict[int, dict[str, int]], datetime]:
    if isinstance(target_fixtures, (str, bytes)) or not isinstance(target_fixtures, Sequence):
        raise ValueError("target_fixtures must be a non-empty sequence")
    fixtures = list(target_fixtures)
    if not fixtures:
        raise ValueError("target_fixtures must be a non-empty sequence")
    if any(not isinstance(fixture, DynamicTeamFixture) for fixture in fixtures):
        raise ValueError("every target fixture must use the P111 DynamicTeamFixture contract")
    match_ids = [_positive_int(fixture.match_id, "fixture match_id") for fixture in fixtures]
    if len(set(match_ids)) != len(match_ids):
        raise ValueError("target fixture match IDs must be unique")
    as_of_values = {
        _naive_datetime(fixture.prediction_as_of, "prediction_as_of") for fixture in fixtures
    }
    if len(as_of_values) != 1:
        raise ValueError("all target fixtures in one P106 run must share prediction_as_of")
    if not isinstance(market_snapshot_ids_by_match, Mapping):
        raise ValueError("market snapshot IDs must be supplied by target match")
    if any(type(match_id) is not int for match_id in market_snapshot_ids_by_match):
        raise ValueError("market snapshot map keys must be integer match IDs")
    if set(market_snapshot_ids_by_match) != set(match_ids):
        raise ValueError("market snapshot map must exactly match target fixtures")
    normalized: dict[int, dict[str, int]] = {}
    all_snapshot_ids: list[int] = []
    for match_id in match_ids:
        raw = market_snapshot_ids_by_match[match_id]
        if not isinstance(raw, Mapping) or set(raw) != set(_OPTIONS):
            raise ValueError(f"match {match_id} requires exactly SPF options 3, 1, and 0")
        ids = {option: _positive_int(raw[option], "odds snapshot ID") for option in _OPTIONS}
        if len(set(ids.values())) != 3:
            raise ValueError(
                f"match {match_id} must use a distinct snapshot ID for each SPF option"
            )
        normalized[match_id] = ids
        all_snapshot_ids.extend(ids.values())
    if len(set(all_snapshot_ids)) != len(all_snapshot_ids):
        raise ValueError("one odds snapshot ID cannot be reused across target options or matches")
    return fixtures, normalized, next(iter(as_of_values))


def _load_market_snapshots(
    conn: Any,
    *,
    fixtures: Sequence[DynamicTeamFixture],
    snapshot_ids_by_match: Mapping[int, Mapping[str, int]],
    prediction_as_of: datetime,
) -> dict[int, _LoadedMarket]:
    match_ids = [fixture.match_id for fixture in fixtures]
    all_snapshot_ids = sorted(
        snapshot_id for values in snapshot_ids_by_match.values() for snapshot_id in values.values()
    )
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, kickoff_time FROM official_matches WHERE id = ANY(%s)", (match_ids,)
        )
        stored_matches = {int(row[0]): row[1] for row in cursor.fetchall()}
        cursor.execute(
            """SELECT id, match_id, play_type, option_code, sp_value, snapshot_time,
                      market_id, raw_hash, is_open, created_at
               FROM official_odds_snapshots WHERE id = ANY(%s)""",
            (all_snapshot_ids,),
        )
        snapshot_rows = cursor.fetchall()
    if set(stored_matches) != set(match_ids):
        raise ValueError("one or more target matches are missing from official_matches")
    for fixture in fixtures:
        actual_kickoff = stored_matches[fixture.match_id]
        if actual_kickoff is None or _naive_datetime(actual_kickoff, "stored kickoff_time") != (
            _naive_datetime(fixture.kickoff_at, "fixture kickoff_at")
        ):
            raise ValueError(
                f"fixture kickoff does not match official_matches for {fixture.match_id}"
            )
    rows_by_id = {int(row[0]): row for row in snapshot_rows}
    if len(rows_by_id) != len(snapshot_rows) or set(rows_by_id) != set(all_snapshot_ids):
        raise ValueError("one or more requested market snapshots are missing or duplicated")

    loaded: dict[int, _LoadedMarket] = {}
    for fixture in fixtures:
        match_id = fixture.match_id
        as_of = _naive_datetime(fixture.prediction_as_of, "prediction_as_of")
        odds: dict[str, float] = {}
        odds_text: dict[str, str] = {}
        times: dict[str, datetime] = {}
        created_times: dict[str, datetime] = {}
        market_ids: set[int | None] = set()
        raw_hashes: set[str] = set()
        ids = dict(snapshot_ids_by_match[match_id])
        for option in _OPTIONS:
            row = rows_by_id[ids[option]]
            (
                _,
                stored_match_id,
                play_type,
                raw_option_code,
                raw_price,
                raw_time,
                market_id,
                raw_hash,
                is_open,
                raw_created_at,
            ) = row
            option_code = _OFFICIAL_OPTION_TO_CANONICAL.get(str(raw_option_code))
            if (
                int(stored_match_id) != match_id
                or str(play_type) != "spf"
                or str(option_code) != option
                or is_open is not True
            ):
                raise ValueError(f"odds snapshot does not match an open {match_id}/spf/{option}")
            snapshot_time = _naive_datetime(raw_time, "odds snapshot_time")
            snapshot_created_at = _naive_datetime(raw_created_at, "odds created_at")
            if snapshot_time > as_of:
                raise ValueError(f"odds snapshot for {match_id}/{option} is after prediction_as_of")
            prediction_as_of_utc = (
                as_of.replace(tzinfo=_OFFICIAL_TIMEZONE).astimezone(UTC).replace(tzinfo=None)
            )
            if snapshot_created_at > prediction_as_of_utc:
                raise ValueError(
                    f"odds snapshot for {match_id}/{option} was stored after prediction_as_of"
                )
            price = float(raw_price)
            if not math.isfinite(price) or price <= 1:
                raise ValueError(
                    f"odds snapshot for {match_id}/{option} is not a finite SPF price above 1"
                )
            if (
                not isinstance(raw_hash, str)
                or len(raw_hash) != 64
                or any(character not in "0123456789abcdef" for character in raw_hash)
            ):
                raise ValueError(f"odds snapshot for {match_id}/{option} has no source hash")
            odds[option] = price
            odds_text[option] = format(raw_price, "f")
            times[option] = snapshot_time
            created_times[option] = snapshot_created_at
            market_ids.add(int(market_id) if market_id is not None else None)
            raw_hashes.add(raw_hash)
        if len(set(times.values())) != 1 or len(market_ids) != 1 or len(raw_hashes) != 1:
            raise ValueError(f"SPF snapshots for {match_id} are not one coherent market capture")
        if as_of - next(iter(times.values())) > timedelta(seconds=_ODDS_MAX_AGE_SECONDS):
            raise ValueError(f"SPF snapshots for {match_id} are older than 45 minutes")
        loaded[match_id] = _LoadedMarket(
            odds=odds,
            odds_text=odds_text,
            snapshot_ids=ids,
            snapshot_times=times,
            snapshot_created_at=created_times,
        )
    return loaded


def _prediction_rows(
    *,
    model_version_id: int,
    prediction: Mapping[str, Any],
    market: _LoadedMarket,
) -> list[dict[str, Any]]:
    probabilities = prediction["spf_probabilities"]
    market_probabilities = normalize_probabilities(market.odds)
    if set(probabilities) != set(_OPTIONS) or set(market_probabilities) != set(_OPTIONS):
        raise ValueError("P111 output and P106 market baseline must contain SPF 3/1/0")
    if not math.isclose(math.fsum(probabilities.values()), 1.0, abs_tol=1e-9):
        raise ValueError("P111 SPF probability vector is not normalized")
    rows = []
    for option in _OPTIONS:
        probability = float(probabilities[option])
        market_probability = float(market_probabilities[option])
        price = market.odds[option]
        if (
            any(not math.isfinite(value) for value in (probability, market_probability))
            or not 0.0 <= probability <= 1.0
            or not 0.0 <= market_probability <= 1.0
        ):
            raise ValueError("P111 or proportional market probability is non-finite")
        rows.append(
            {
                "match_id": int(prediction["match_id"]),
                "model_version_id": model_version_id,
                "odds_snapshot_id": market.snapshot_ids[option],
                "feature_snapshot_id": None,
                "predict_time": _p106_timestamp_text(
                    prediction["prediction_as_of"], "prediction_as_of"
                ),
                "play_type": "spf",
                "option_code": option,
                "raw_model_probability": probability,
                "model_probability": probability,
                "market_probability": market_probability,
                "adjusted_probability": probability,
                "fair_odds": safe_fair_odds(probability),
                "ev": probability * price - 1.0,
                "break_even_probability": 1.0 / price,
                "market_edge": probability - market_probability,
                "breakeven_edge": probability - 1.0 / price,
                "validation_status": "invalid",
                "validation_errors": ["research_only_shadow_not_publishable"],
                "calculation_version": CALCULATION_VERSION,
                "uncertainty_reason": {
                    "rollout_mode": "shadow",
                    "candidate_sha256": prediction["candidate_sha256"],
                    "prediction_context_sha256": prediction["prediction_context_sha256"],
                    "home_team_coverage": prediction["home_team_coverage"],
                    "away_team_coverage": prediction["away_team_coverage"],
                },
            }
        )
    return rows


def run_dynamic_team_p106_shadow(
    conn: Any,
    *,
    parent_training_manifest: Mapping[str, Any],
    season_context_by_match: Mapping[int, SeasonMatchContext | Mapping[str, Any] | None],
    competition_id: int,
    competition_season_id: int,
    target_fixtures: Sequence[DynamicTeamFixture],
    market_snapshot_ids_by_match: Mapping[int, Mapping[str, int]],
    release_id: str,
    config: DynamicTeamConfig | None = None,
    promoted_team_evidence: Mapping[int, PromotionEvidence | Mapping[str, Any]] | None = None,
    run_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Fit and store one inactive P111 candidate through existing P106 storage.

    This performs no provider or scheduler work. Invoke only with an isolated
    research database: P106 completed groups are intentionally visible in
    generic prediction views even while their model version is inactive.
    """
    if getattr(conn, "autocommit", False) is True:
        raise ValueError("P111 P106 integration requires autocommit=False")
    if not callable(getattr(conn, "get_transaction_status", None)):
        raise TypeError("P111 P106 integration requires a psycopg2 connection")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("P111 P106 integration requires an idle connection")
    _require_isolated_research_database(conn)
    if not isinstance(release_id, str) or not release_id.strip() or len(release_id) > 128:
        raise ValueError("release_id must contain 1 to 128 characters")
    try:
        normalized_run_id = uuid.UUID(str(run_id)) if run_id is not None else uuid.uuid4()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("run_id must be a valid UUID") from exc

    fixtures, snapshot_ids, prediction_as_of = _validate_fixture_set(
        target_fixtures, market_snapshot_ids_by_match
    )
    projection = project_p106_manifest_to_season(
        parent_training_manifest,
        season_context_by_match,
        competition_id=competition_id,
        competition_season_id=competition_season_id,
    )
    model = fit_dynamic_team_challenger(
        projection.manifest,
        projection.selected_contexts,
        config=config,
        promoted_team_evidence=promoted_team_evidence,
    )
    predictions_by_match = {
        fixture.match_id: predict_dynamic_team_challenger(model, fixture) for fixture in fixtures
    }
    try:
        markets = _load_market_snapshots(
            conn,
            fixtures=fixtures,
            snapshot_ids_by_match=snapshot_ids,
            prediction_as_of=prediction_as_of,
        )
    finally:
        # Market validation is a read-only transaction; keep retries on the same
        # dedicated connection safe even when an input snapshot is rejected.
        conn.rollback()
    prepared_rows = {
        match_id: _prediction_rows(
            model_version_id=0,
            prediction=prediction,
            market=markets[match_id],
        )
        for match_id, prediction in predictions_by_match.items()
    }

    parameters = _model_artifact_parameters(model, projection)
    model_version_id = _persist_inactive_model(
        conn, parameters=parameters, manifest=projection.manifest
    )
    artifact_identity = build_model_artifact_identity(model_version_id, MODEL_NAME, parameters)
    if artifact_identity.get("provenance_status") != "complete":
        raise ValueError("P111 shadow model artifact identity is incomplete")
    # The IDs are now fixed; rows were otherwise fully validated before any DB write.
    for rows in prepared_rows.values():
        for row in rows:
            row["model_version_id"] = model_version_id

    fixture_inputs = []
    for fixture in sorted(fixtures, key=lambda item: item.match_id):
        match_id = fixture.match_id
        prediction = predictions_by_match[match_id]
        market = markets[match_id]
        context = {
            "competition_id": fixture.competition_id,
            "competition_season_id": fixture.competition_season_id,
            "home_team_id": fixture.home_team_id,
            "away_team_id": fixture.away_team_id,
            "kickoff_at": _datetime_text(_naive_datetime(fixture.kickoff_at, "kickoff_at")),
            "neutral_venue": fixture.neutral_venue,
            "season_membership_evidence_sha256": fixture.season_membership_evidence_sha256,
            "season_membership_available_at": _datetime_text(
                _naive_datetime(fixture.season_membership_available_at, "membership available_at")
            ),
            "venue_evidence_sha256": fixture.venue_evidence_sha256,
            "venue_evidence_available_at": _datetime_text(
                _naive_datetime(fixture.venue_evidence_available_at, "venue available_at")
            ),
        }
        fixture_inputs.append(
            {
                "match_id": match_id,
                "fixture_context": context,
                "prediction_as_of": prediction["prediction_as_of"],
                "prediction_context_sha256": prediction["prediction_context_sha256"],
                "prediction_sha256": prediction["prediction_sha256"],
                "odds_by_option": market.odds_text,
                "odds_snapshot_ids": market.snapshot_ids,
                "odds_snapshot_times": {
                    option: _datetime_text(value) for option, value in market.snapshot_times.items()
                },
                "odds_snapshot_created_at": {
                    option: _datetime_text(value)
                    for option, value in market.snapshot_created_at.items()
                },
            }
        )
    input_manifest = {
        "schema_version": "p111.dynamic-team-p106-input/v1",
        "rollout_mode": "shadow",
        "model_name": MODEL_NAME,
        "candidate_sha256": model.candidate_sha256,
        "parent_training_manifest_sha256": projection.parent_training_manifest_sha256,
        "training_manifest_sha256": model.training_manifest_sha256,
        "competition_id": model.competition_id,
        "competition_season_id": model.competition_season_id,
        "fit_cutoff": _datetime_text(model.fit_cutoff),
        "prediction_as_of": _datetime_text(prediction_as_of),
        "projection_policy": PROJECTION_VERSION,
        "projection_sha256": projection.projection_sha256,
        "projection_context_sha256": projection.season_context_sha256,
        "season_context_sha256": model.season_context_sha256,
        "projection_audit": list(projection.audit),
        "match_ids": [fixture.match_id for fixture in fixtures],
        "markets": [
            [fixture.match_id, "spf"]
            for fixture in sorted(fixtures, key=lambda item: item.match_id)
        ],
        "fixtures": fixture_inputs,
    }
    model_manifest = [artifact_identity]
    source_root = Path(__file__).resolve().parents[1]
    code_fingerprint = fingerprint_runtime_sources(source_root, _RUNTIME_SOURCE_PATHS)

    run_created = False
    try:
        create_prediction_run(
            conn,
            run_id=normalized_run_id,
            ai_job_run_id=None,
            release_id=release_id.strip(),
            code_fingerprint=code_fingerprint,
            model_manifest=model_manifest,
            input_manifest=input_manifest,
            provenance_status="complete",
        )
        run_created = True
        group_ids: list[str] = []
        for fixture in fixtures:
            match_id = fixture.match_id
            market = markets[match_id]
            prediction = predictions_by_match[match_id]
            group_id = store_prediction_group(
                conn,
                run_id=normalized_run_id,
                metadata={
                    "match_id": match_id,
                    "model_version_id": model_version_id,
                    "play_type": "spf",
                    "market_variant": "",
                    "predict_time": _p106_timestamp_text(
                        prediction["prediction_as_of"], "prediction_as_of"
                    ),
                    "expected_options": list(_OPTIONS),
                    "score_matrix": prediction["score_matrix"],
                    "odds_snapshot_ids": market.snapshot_ids,
                    "odds_snapshot_times": {
                        option: _datetime_text(value)
                        for option, value in market.snapshot_times.items()
                    },
                    "artifact_identity": artifact_identity,
                    "provenance_status": "complete",
                },
                predictions=prepared_rows[match_id],
            )
            group_ids.append(str(group_id))
        finalize_prediction_run(
            conn,
            run_id=normalized_run_id,
            run_status="completed",
            output_summary={
                "expected_groups": len(fixtures),
                "completed_groups": len(group_ids),
                "skipped_groups": 0,
                "missing_groups": [],
                "input_updates_skipped": 0,
                "completion_reason": "p111_shadow_predictions_completed",
            },
        )
    except Exception as exc:
        conn.rollback()
        if run_created:
            try:
                fail_prediction_run(
                    conn,
                    normalized_run_id,
                    f"P111 shadow run failed: {type(exc).__name__}: {exc}",
                )
            except Exception:
                conn.rollback()
        raise
    return {
        "status": "completed",
        "rollout_mode": "shadow",
        "publishable": False,
        "run_id": str(normalized_run_id),
        "model_version_id": model_version_id,
        "model_name": MODEL_NAME,
        "candidate_sha256": model.candidate_sha256,
        "artifact_sha256": parameters["artifact_sha256"],
        "parent_training_manifest_sha256": projection.parent_training_manifest_sha256,
        "training_manifest_sha256": model.training_manifest_sha256,
        "projection_sha256": projection.projection_sha256,
        "group_ids": group_ids,
        "prediction_count": len(group_ids),
    }


def evaluate_dynamic_team_p106_shadow(
    conn: Any,
    *,
    prediction_run_id: uuid.UUID | str,
    name: str,
) -> dict[str, Any]:
    """Replay settled P111 groups with P106's evaluator and research storage.

    Pending official results remain unevaluated: the P106 replay evaluator
    refuses to produce a report when no settled paired observation exists.
    """
    if getattr(conn, "autocommit", False) is True:
        raise ValueError("P111 evaluation storage requires autocommit=False")
    if not callable(getattr(conn, "get_transaction_status", None)):
        raise TypeError("P111 evaluation storage requires a psycopg2 connection")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("P111 evaluation storage requires an idle connection")
    _require_isolated_research_database(conn)
    normalized_run_id = str(uuid.UUID(str(prediction_run_id)))
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT run_status, model_manifest FROM model_prediction_runs WHERE id=%s",
            (normalized_run_id,),
        )
        row = cursor.fetchone()
    conn.commit()
    if row is None:
        raise ValueError("P111 prediction run was not found")
    run_status, model_manifest = row
    if run_status not in {"completed", "partial"}:
        raise ValueError("P111 prediction run is not terminal and publishable to replay")
    if (
        not isinstance(model_manifest, list)
        or len(model_manifest) != 1
        or model_manifest[0].get("model_name") != MODEL_NAME
    ):
        raise ValueError("prediction run is not an isolated P111 dynamic-team run")
    model_version_id = model_manifest[0].get("model_version_id")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT model_name, is_active, parameters_json FROM model_versions WHERE id=%s",
            (model_version_id,),
        )
        version_row = cursor.fetchone()
    conn.commit()
    if version_row is None:
        raise ValueError("P111 model version was not found")
    stored_name, is_active, parameters = version_row
    if (
        stored_name != MODEL_NAME
        or is_active is not False
        or not isinstance(parameters, Mapping)
        or parameters.get("rollout_mode") != "shadow"
        or parameters.get("publishable") is not False
    ):
        raise ValueError("P111 model version is not an inactive shadow candidate")

    from scripts.backtest_engine import evaluate_prediction_replay, store_research_evaluation_run

    report = evaluate_prediction_replay(conn, normalized_run_id)
    if report.get("official_prediction_writes") != 0 or not report.get("predictions"):
        raise ValueError("P106 replay did not return read-only P111 research observations")
    if any(
        item.get("artifact_identity", {}).get("model_name") != MODEL_NAME
        for item in report["predictions"]
    ):
        raise ValueError("P106 replay returned a non-P111 model identity")
    evaluation_run_id = store_research_evaluation_run(conn, report, name=name)
    return {
        "status": "evaluated",
        "prediction_run_id": normalized_run_id,
        "evaluation_run_id": evaluation_run_id,
        "sample_count": report["sample_count"],
        "report": report,
    }
