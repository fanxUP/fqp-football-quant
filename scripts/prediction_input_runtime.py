"""Bounded observed-input consumers for the existing feature build task.

Owns a borrowed idle connection's transactions. No source/network/cache calls,
official prediction, recommendation, ticket or financial writes.
"""

from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from scripts.data_catalog import get_field_resolution_policy
from scripts.feature_batch_storage import load_feature_batch
from scripts.observation_storage import capture_observation_cutoff
from scripts.observed_feature_pipeline import build_observed_feature_batch
from scripts.observed_maher_shadow import build_observed_maher_shadow
from scripts.prediction_input_revisions import (
    _blocked_outcome,
    _context,
    _current,
    _read_transaction,
    claim_prediction_input_revisions,
    complete_blocked_prediction_input,
    complete_prediction_input_revision,
)
from scripts.prediction_input_updates import (
    InputUpdateLeaseLost,
    InputUpdateSuperseded,
    _match_filter,
    release_input_update,
)

CONSUMERS = {play: f"observed-readiness/{play}/v1" for play in ("spf", "rqspf")}
MAHER_SHADOW_CONSUMER = "observed-maher-shadow/spf/v1"
_SHADOW_FIELDS = (
    "temperature_2m",
    "home_lineup_confirmed",
    "away_lineup_confirmed",
    "home_key_absence_count",
    "away_key_absence_count",
)


def _bounded_transaction(conn: Any) -> None:
    _read_transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name,setting::bigint FROM pg_settings "
            "WHERE name IN ('statement_timeout','lock_timeout')"
        )
        current = dict(cur.fetchall())
        for name, ceiling in (("statement_timeout", 5000), ("lock_timeout", 500)):
            value = min(current[name], ceiling) if current[name] else ceiling
            cur.execute("SELECT set_config(%s,%s,true)", (name, f"{value}ms"))


def _streams(match_id: int, state: dict) -> list[dict]:
    streams = []
    for field in ("weather.temperature_2m", "lineup.starters", "injuries.complete_report"):
        policy = get_field_resolution_policy(field)
        subjects = (
            ["forecast"]
            if policy["subject"] == "forecast"
            else [f"team:{state[side + '_ids'][0]}" for side in ("home", "away")]
        )
        for source in policy["sources"]:
            for subject in subjects:
                streams.append(
                    dict(
                        match_id=match_id,
                        source_id=source,
                        domain=policy["domain"],
                        subject_key=subject,
                    )
                )
    return streams


def _deferred(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            InputUpdateLeaseLost,
            InputUpdateSuperseded,
            psycopg2.errors.LockNotAvailable,
            psycopg2.errors.QueryCanceled,
        ),
    )


def _active_maher_model(conn: Any) -> tuple[int | None, dict | None, str | None]:
    """Read exactly one active Maher version without poisoning the caller transaction on ACL denial."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT observed_maher_model_lookup")
        try:
            cur.execute(
                "SELECT id,parameters_json FROM model_versions "
                "WHERE model_name='maher_poisson' AND is_active=true ORDER BY id DESC LIMIT 2"
            )
            rows = cur.fetchall()
        except psycopg2.errors.InsufficientPrivilege:
            cur.execute("ROLLBACK TO SAVEPOINT observed_maher_model_lookup")
            cur.execute("RELEASE SAVEPOINT observed_maher_model_lookup")
            return None, None, "model_lookup_forbidden"
        cur.execute("RELEASE SAVEPOINT observed_maher_model_lookup")
    if not rows:
        return None, None, "no_active_maher_version"
    if len(rows) != 1:
        return None, None, "ambiguous_active_maher_versions"
    version_id, parameters = rows[0]
    if type(version_id) is not int or version_id <= 0 or not isinstance(parameters, dict):
        return (
            version_id if type(version_id) is int else None,
            None,
            "invalid_active_maher_parameters",
        )
    return version_id, parameters, None


def _maher_shadow_ref(conn: Any, *, batch_id: int, match_id: int, input_version: int) -> dict:
    batch = load_feature_batch(conn, batch_id)
    if batch is None or batch["match_id"] != match_id:
        raise ValueError("exact feature batch is required for Maher shadow execution")
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        as_of = cur.fetchone()[0]
    from scripts.observed_feature_pipeline import load_observed_feature_input

    feature_input = load_observed_feature_input(
        conn,
        batch_id=batch_id,
        match_id=match_id,
        as_of=as_of,
        feature_columns=_SHADOW_FIELDS,
        required_fields=(),
    )
    version_id, parameters, model_reason = _active_maher_model(conn)
    result = build_observed_maher_shadow(
        model_version_id=version_id,
        model_parameters=parameters,
        feature_input=feature_input,
        batch=batch,
        input_version=input_version,
        as_of=as_of,
    )
    if model_reason is not None:
        result.update(status="model_unavailable", reason=model_reason)
    return result


def drain_prediction_input_updates(
    conn: Any, *, match_id: int | None = None, limit: int = 8
) -> dict:
    """Process bounded readiness and SPF shadow claims, then return; never retry in a loop.

    Readiness consumers continue to use profiles=() until P106 artifact
    compatibility is implemented. The independent Maher consumer stores only
    a shadow result reference and never replaces a legacy prediction.
    """
    _match_filter(match_id)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("limit must be 1..32")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("consumer requires an idle exclusively borrowed connection")
    result: dict[str, Any] = dict(
        status="ok",
        claimed=0,
        completed=0,
        blocked=0,
        deferred=0,
        failed=0,
        shadow_claimed=0,
        shadow_completed=0,
        shadow_blocked=0,
        shadow_deferred=0,
        shadow_failed=0,
        errors=[],
    )
    for play, key in CONSUMERS.items():
        try:
            _bounded_transaction(conn)
            claims = claim_prediction_input_revisions(
                conn, consumer_key=key, limit=limit, match_id=match_id
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            result["deferred" if _deferred(exc) else "failed"] += 1
            if not _deferred(exc):
                result["errors"].append(
                    dict(
                        match_id=match_id,
                        play_type=play,
                        phase="claim",
                        error_type=type(exc).__name__,
                    )
                )
            continue
        result["claimed"] += len(claims)
        for claim in claims:
            try:
                _bounded_transaction(conn)
                at, state, _, _ = _current(conn, claim.match_id, play)
                context = _context(claim.match_id, play, at, state)
                if _blocked_outcome(context) is not None:
                    complete_blocked_prediction_input(conn, claim, play_type=play)
                    conn.commit()
                    result["blocked"] += 1
                    continue
                cutoff = capture_observation_cutoff(conn, streams=_streams(claim.match_id, state))
                # Cutoff+batch+revision+receipt all commit together. Claim was
                # committed earlier; failures leave no orphan runtime batch.
                if cutoff.as_of >= context.kickoff_at:
                    conn.rollback()
                    _bounded_transaction(conn)
                    complete_blocked_prediction_input(conn, claim, play_type=play)
                    conn.commit()
                    result["blocked"] += 1
                    continue
                batch_id = build_observed_feature_batch(
                    conn,
                    match_id=claim.match_id,
                    cutoff=cutoff,
                    context=dict(
                        home_team_id=state["home_ids"][0],
                        away_team_id=state["away_ids"][0],
                        kickoff_at=context.kickoff_at,
                    ),
                )
                complete_prediction_input_revision(
                    conn, claim, batch_id=batch_id, play_type=play, profiles=()
                )
                conn.commit()
                result["completed"] += 1
            except Exception as exc:
                conn.rollback()
                deferred = _deferred(exc)
                result["deferred" if deferred else "failed"] += 1
                if not deferred:
                    result["errors"].append(
                        dict(match_id=claim.match_id, play_type=play, error_type=type(exc).__name__)
                    )
                try:
                    _bounded_transaction(conn)
                    release_input_update(conn, claim)
                    conn.commit()
                except psycopg2.Error:
                    conn.rollback()  # Lease expiry permits later reclamation.
    # This independent consumer key preserves old readiness receipts while
    # making each shadow result immutable and separately replayable.
    try:
        _bounded_transaction(conn)
        shadow_claims = claim_prediction_input_revisions(
            conn, consumer_key=MAHER_SHADOW_CONSUMER, limit=limit, match_id=match_id
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        result["shadow_deferred" if _deferred(exc) else "shadow_failed"] += 1
        if not _deferred(exc):
            result["errors"].append(
                dict(
                    match_id=match_id,
                    play_type="spf",
                    consumer_key=MAHER_SHADOW_CONSUMER,
                    phase="claim",
                    error_type=type(exc).__name__,
                )
            )
        shadow_claims = []
    result["shadow_claimed"] += len(shadow_claims)
    for claim in shadow_claims:
        try:
            _bounded_transaction(conn)
            at, state, _, _ = _current(conn, claim.match_id, "spf")
            context = _context(claim.match_id, "spf", at, state)
            if _blocked_outcome(context) is not None:
                complete_blocked_prediction_input(conn, claim, play_type="spf")
                conn.commit()
                result["shadow_blocked"] += 1
                continue
            cutoff = capture_observation_cutoff(conn, streams=_streams(claim.match_id, state))
            if cutoff.as_of >= context.kickoff_at:
                conn.rollback()
                _bounded_transaction(conn)
                complete_blocked_prediction_input(conn, claim, play_type="spf")
                conn.commit()
                result["shadow_blocked"] += 1
                continue
            batch_id = build_observed_feature_batch(
                conn,
                match_id=claim.match_id,
                cutoff=cutoff,
                context=dict(
                    home_team_id=state["home_ids"][0],
                    away_team_id=state["away_ids"][0],
                    kickoff_at=context.kickoff_at,
                ),
            )
            shadow = _maher_shadow_ref(
                conn,
                batch_id=batch_id,
                match_id=claim.match_id,
                input_version=claim.input_version,
            )
            complete_prediction_input_revision(
                conn,
                claim,
                batch_id=batch_id,
                play_type="spf",
                profiles=(),
                extra_result_refs={"maher_shadow": shadow},
            )
            conn.commit()
            result["shadow_completed"] += 1
        except Exception as exc:
            conn.rollback()
            deferred = _deferred(exc)
            result["shadow_deferred" if deferred else "shadow_failed"] += 1
            if not deferred:
                result["errors"].append(
                    dict(
                        match_id=claim.match_id,
                        play_type="spf",
                        consumer_key=MAHER_SHADOW_CONSUMER,
                        error_type=type(exc).__name__,
                    )
                )
            try:
                _bounded_transaction(conn)
                release_input_update(conn, claim)
                conn.commit()
            except psycopg2.Error:
                conn.rollback()  # Lease expiry permits later reclamation.
    if result["failed"] or result["shadow_failed"]:
        result["status"] = "failed"
    return result
