"""Bounded observed-readiness consumer for the existing feature build task.

Owns a borrowed idle connection's transactions. No source/network/cache calls,
model inference, independent artifact declaration, ticket or financial writes.
"""

from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from scripts.data_catalog import get_field_resolution_policy
from scripts.observation_storage import capture_observation_cutoff
from scripts.observed_feature_pipeline import build_observed_feature_batch
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


def drain_prediction_input_updates(
    conn: Any, *, match_id: int | None = None, limit: int = 8
) -> dict:
    """Process <=limit claims per fixed play, then return; never retry in a loop.

    profiles=() is deliberate: artifact compatibility is P106. Results here are
    non-independent readiness records, not replacement legacy predictions.
    """
    _match_filter(match_id)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("limit must be 1..32")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("consumer requires an idle exclusively borrowed connection")
    result: dict[str, Any] = dict(
        status="ok", claimed=0, completed=0, blocked=0, deferred=0, failed=0, errors=[]
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
    if result["failed"]:
        result["status"] = "failed"
    return result
