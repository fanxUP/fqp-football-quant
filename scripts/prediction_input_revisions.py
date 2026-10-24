"""Explicit persisted input-readiness pilot, never financial/model publication.

Callers commit claims before computation and own every transaction. A configured
consumer key binds one play/profile contract. Always validate current DB state
on reads; cached policy payloads alone cannot authorize recommendations.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from scripts.data_catalog import get_data_source
from scripts.feature_batch_storage import load_feature_batch
from scripts.observation_storage import _canonical, _transaction
from scripts.observed_feature_pipeline import _time
from scripts.prediction_input_policy import (
    InputProfile,
    PredictionContext,
    load_prediction_input_mode,
)
from scripts.prediction_input_updates import (
    InputUpdateClaim,
    InputUpdateSuperseded,
    _consumer,
    _match_filter,
    claim_input_updates,
    complete_input_update,
)

MAHER_SHADOW_CONSUMER = "observed-maher-shadow/spf/v2"


def _current(conn: Any, match_id: int, play_type: str) -> tuple[datetime, dict, int, datetime]:
    """One READ COMMITTED statement observes head, official state and DB time."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH stamp AS MATERIALIZED (SELECT clock_timestamp() AS at)
            SELECT stamp.at,jsonb_build_object(
                'source_match_id',m.source_match_id,'business_date',m.business_date,
                'official_match_code',m.official_match_code,
                'home_team_name',m.home_team_name,'away_team_name',m.away_team_name,
                'kickoff_at',m.kickoff_time AT TIME ZONE 'Asia/Shanghai',
                'sale_stop_at',m.sale_stop_time AT TIME ZONE 'Asia/Shanghai',
                'sale_status',m.sale_status,'match_status',m.match_status,
                'home_ids',(SELECT COALESCE(jsonb_agg(DISTINCT t.id ORDER BY t.id),'[]')
                    FROM teams t JOIN team_aliases a ON a.team_id=t.id
                    WHERE a.alias_name=btrim(m.home_team_name) AND a.source_name=%(namespace)s),
                'away_ids',(SELECT COALESCE(jsonb_agg(DISTINCT t.id ORDER BY t.id),'[]')
                    FROM teams t JOIN team_aliases a ON a.team_id=t.id
                    WHERE a.alias_name=btrim(m.away_team_name) AND a.source_name=%(namespace)s),
                'markets',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id',mk.id,'handicap',mk.handicap,'is_open',mk.is_open,
                    'market_status',mk.market_status) ORDER BY mk.id)
                    FROM official_markets mk WHERE mk.match_id=m.id AND mk.play_type=%(play)s),'[]'),
                'odds',COALESCE((SELECT jsonb_agg(to_jsonb(o) ORDER BY o.option_code) FROM (
                    SELECT DISTINCT ON (os.option_code) os.id,os.market_id,os.option_code,
                        os.sp_value,os.handicap,os.is_open,os.snapshot_time
                    FROM official_odds_snapshots os WHERE os.match_id=m.id AND os.play_type=%(play)s
                        AND os.snapshot_time<=timezone('Asia/Shanghai',stamp.at)
                    ORDER BY os.option_code,os.snapshot_time DESC,os.id DESC
                ) o),'[]')),
                d.input_version,d.changed_at
            FROM official_matches m JOIN prediction_input_dirty_matches d ON d.match_id=m.id
            CROSS JOIN stamp WHERE m.id=%(match)s
            """,
            dict(
                match=match_id,
                play=play_type,
                namespace=get_data_source("sporttery")["alias_namespace"],
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("observed official match is absent")
    return row


def _context(match_id: int, play: str, at: datetime, state: dict) -> PredictionContext:
    markets, rows = state["markets"], state["odds"]
    market = markets[0] if len(markets) == 1 else {}
    codes = {"h": "3", "d": "1", "a": "0", "3": "3", "1": "1", "0": "0"}
    odds, refs = {}, {}
    for row in rows:
        code = codes.get(row["option_code"])
        if code is not None and code not in odds:
            odds[code], refs[code] = row["sp_value"], row["id"]
    coherent = len(rows) == 3 and len({r["snapshot_time"] for r in rows}) == 1
    coherent = coherent and all(
        r["market_id"] == market.get("id")
        and r["is_open"] is True
        and r["handicap"] == market.get("handicap")
        for r in rows
    )
    if not coherent:
        odds, refs = {}, {}
    home, away = state["home_ids"], state["away_ids"]
    identity = (
        bool((state["source_match_id"] or "").strip())
        and len(home) == len(away) == 1
        and home != away
    )
    return PredictionContext(
        match_id=match_id,
        play_type=play,
        decision_at=at,
        kickoff_at=_time(state["kickoff_at"]),
        sale_stop_at=_time(state["sale_stop_at"]) if state["sale_stop_at"] else None,
        identity_verified=identity,
        sale_status=state["sale_status"] or "unknown",
        match_status=state["match_status"] or "unknown",
        market_open=market.get("is_open") is True and market.get("market_status") == "open",
        odds_by_option=odds,
        odds_snapshot_ids=refs,
        handicap=market.get("handicap"),
    )


def _expiry(conn: Any, batch: dict, max_age: int) -> datetime:
    boundaries = [batch["cutoff"].as_of + timedelta(seconds=max_age)]
    for field in batch["features"].values():
        resolution = field.get("derivation", {}).get("resolution", {})
        for candidate in resolution.get("candidates", []):
            if candidate["index"] in resolution.get("selected_indexes", []):
                boundaries.append(_time(candidate["expires_at"]))
    # Already ingested but future-available evidence/odds can change the decision
    # without another INSERT. Invalidate conservatively at that exact boundary.
    with conn.cursor() as cur:
        cur.execute(
            """SELECT min(at) FROM (
                SELECT r.available_at at FROM observation_revisions r JOIN observation_streams s
                    ON s.id=r.stream_id WHERE s.match_id=%s
                UNION ALL SELECT c.available_at FROM observation_checks c JOIN observation_streams s
                    ON s.id=c.stream_id WHERE s.match_id=%s
                UNION ALL SELECT snapshot_time AT TIME ZONE 'Asia/Shanghai'
                    FROM official_odds_snapshots WHERE match_id=%s
            ) times WHERE at>%s""",
            (batch["match_id"], batch["match_id"], batch["match_id"], batch["cutoff"].as_of),
        )
        future = cur.fetchone()[0]
    if future:
        boundaries.append(future)
    return min(boundaries)


def _read_transaction(conn: Any) -> None:
    _transaction(conn)
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_isolation")
        if cur.fetchone()[0] != "read committed":
            raise ValueError("current input decisions require READ COMMITTED")


def complete_prediction_input_revision(
    conn: Any,
    claim: InputUpdateClaim,
    *,
    batch_id: int,
    play_type: str,
    profiles: Sequence[InputProfile],
    extra_result_refs: dict | None = None,
    max_age_seconds: int = 60,
) -> dict:
    """Atomically retain mode decision, exact batch/cutoff and the 109 receipt.

    No artifact execution/probabilities or recommendation promotion. Late work
    is retained as research_only and cannot later revive through a reopened sale.
    Duplicate completion always returns the original persisted revision reference.
    """
    if play_type not in ("spf", "rqspf"):
        raise ValueError("pilot supports explicit spf/rqspf only")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
        raise ValueError("max_age_seconds must be 1..300")
    if extra_result_refs is not None:
        if not isinstance(extra_result_refs, dict) or set(extra_result_refs) - {"maher_shadow"}:
            raise ValueError("only the bounded Maher shadow result reference is supported")
        _canonical(extra_result_refs, 8192)
    _read_transaction(conn)

    def publish(conn: Any, current_claim: InputUpdateClaim) -> dict:
        batch = load_feature_batch(conn, batch_id)
        if batch is None or batch["match_id"] != current_claim.match_id:
            raise ValueError("exact complete batch for claimed match required")
        at, state, version, changed = _current(conn, current_claim.match_id, play_type)
        if version != current_claim.input_version or batch["cutoff"].as_of < changed:
            raise InputUpdateSuperseded("batch cutoff predates claimed input version")
        context = _context(current_claim.match_id, play_type, at, state)
        declared = (
            batch["features"].get("temperature_2m", {}).get("derivation", {}).get("context", {})
        )
        matches = (
            state["home_ids"] == [declared.get("home_team_id")]
            and state["away_ids"] == [declared.get("away_team_id")]
            and _time(declared.get("kickoff_at")) == context.kickoff_at
        )
        decision = load_prediction_input_mode(
            conn, batch_id=batch_id, context=context, profiles=profiles
        )
        expiry = _expiry(conn, batch, max_age_seconds)
        if current_claim.consumer_key == MAHER_SHADOW_CONSUMER:
            decision["restrictions"].append("shadow_only")
        reasons = list(decision["restrictions"])
        if not matches:
            reasons.append("batch_official_context_mismatch")
        if at >= expiry:
            reasons.append("input_expired")
        decision["recommendation_eligible"] = not reasons
        # Recheck time/state after derivation so a boundary crossed during work
        # never persists an actionable revision based on the earlier timestamp.
        final_at, final_state, _, _ = _current(conn, current_claim.match_id, play_type)
        if final_state != state:
            reasons.append("official_context_changed")
        if final_at >= expiry:
            reasons.append("input_expired")
        if final_at >= context.kickoff_at:
            reasons.append("kickoff_reached")
        if context.sale_stop_at is not None and final_at >= context.sale_stop_at:
            reasons.append("sale_closed")
        reasons = list(dict.fromkeys(reasons))
        decision["recommendation_eligible"] = not reasons
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO prediction_input_revisions(consumer_key,match_id,input_version,play_type,
                    feature_batch_id,observation_cutoff_id,decision,official_context,research_only,
                    invalidation_reasons,valid_until) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)
                    RETURNING id""",
                (
                    current_claim.consumer_key,
                    current_claim.match_id,
                    current_claim.input_version,
                    play_type,
                    batch_id,
                    batch["cutoff_id"],
                    _canonical(decision, 65536),
                    _canonical(state, 16384),
                    bool(reasons),
                    _canonical(reasons, 4096),
                    expiry,
                ),
            )
            refs = {"input_revision_id": int(cur.fetchone()[0])}
            if extra_result_refs:
                shadow = extra_result_refs.get("maher_shadow")
                if (
                    not isinstance(shadow, dict)
                    or shadow.get("match_id") != current_claim.match_id
                    or shadow.get("input_version") != current_claim.input_version
                    or shadow.get("feature_batch_id") != batch_id
                    or shadow.get("observation_cutoff_id") != batch["cutoff_id"]
                    or shadow.get("play_type") != play_type
                ):
                    raise ValueError("shadow result reference does not match the exact input claim")
                refs.update(extra_result_refs)
            return refs

    return complete_input_update(conn, claim, publish)


def load_prediction_input_revision(conn: Any, revision_id: int) -> dict | None:
    """Validate a retained revision against current DB state, never a cache head.

    recommendation_eligible is an input gate only; the existing artifact, news,
    release, price and financial/ticket gates still apply outside this pilot.
    """
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError("positive revision ID required")
    _read_transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT match_id,input_version,play_type,feature_batch_id,observation_cutoff_id::text,"
            "decision,official_context,research_only,invalidation_reasons,valid_until "
            "FROM prediction_input_revisions WHERE id=%s",
            (revision_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    match_id, version, play, batch, cutoff, decision, official, research, retained, expiry = row
    at, state, current_version, _ = _current(conn, match_id, play)
    reasons = list(retained)
    if version != current_version:
        reasons.append("input_version_changed")
    if official != state:
        reasons.append("official_context_changed")
    if at >= expiry:
        reasons.append("input_expired")
    context = _context(match_id, play, at, state)
    if at >= context.kickoff_at:
        reasons.append("kickoff_reached")
    if context.sale_status != "selling" or (
        context.sale_stop_at is not None and at >= context.sale_stop_at
    ):
        reasons.append("sale_closed")
    if context.sale_stop_at is None:
        reasons.append("sale_deadline_unknown")
    reasons = list(dict.fromkeys(reasons))
    return dict(
        id=revision_id,
        match_id=match_id,
        input_version=version,
        play_type=play,
        feature_batch_id=batch,
        observation_cutoff_id=cutoff,
        decision=decision,
        research_only=research,
        valid_until=expiry.astimezone(UTC).isoformat(),
        status="invalidated" if reasons else "current",
        invalidation_reasons=reasons,
        recommendation_eligible=not research
        and not reasons
        and decision["recommendation_eligible"],
    )


_IDENTITY_RECHECK_SECONDS = 60


def _blocked_outcome(
    context: PredictionContext, *, consumer_key: str | None = None
) -> tuple[str, list[str]] | None:
    reasons = []
    if context.decision_at >= context.kickoff_at:
        reasons.append("kickoff_reached")
    if consumer_key != MAHER_SHADOW_CONSUMER:
        if context.sale_status != "selling" or (
            context.sale_stop_at is not None and context.decision_at >= context.sale_stop_at
        ):
            reasons.append("sale_closed")
        if context.sale_stop_at is None:
            reasons.append("sale_deadline_unknown")
    if context.match_status.lower() not in ("scheduled", "selling", "not_started"):
        reasons.append("match_not_scheduled")
    if reasons:
        return "not_actionable", reasons
    if not context.identity_verified:
        return "awaiting_verification", ["identity_unverified"]
    return None


def complete_blocked_prediction_input(
    conn: Any, claim: InputUpdateClaim, *, play_type: str
) -> dict:
    """Retain a fenced, non-actionable receipt when no legal batch can be built.

    Never a revision or publication authority. Identity cases are periodically
    rechecked by the existing task; closed fixtures need a new official update.
    """
    if play_type not in ("spf", "rqspf"):
        raise ValueError("explicit supported play required")
    _read_transaction(conn)

    def publish(conn: Any, current_claim: InputUpdateClaim) -> dict:
        at, state, _, _ = _current(conn, current_claim.match_id, play_type)
        blocked = _blocked_outcome(
            _context(current_claim.match_id, play_type, at, state),
            consumer_key=current_claim.consumer_key,
        )
        if blocked is None:
            raise InputUpdateSuperseded("match is buildable; capture a new cutoff")
        outcome, reasons = blocked
        return dict(
            outcome=outcome,
            reasons=reasons,
            play_type=play_type,
            research_only=True,
            recommendation_eligible=False,
            observed_at=at.isoformat(),
        )

    return complete_input_update(conn, claim, publish)


def claim_prediction_input_revisions(
    conn: Any,
    *,
    consumer_key: str,
    limit: int = 8,
    lease_seconds: int = 120,
    match_id: int | None = None,
) -> list[InputUpdateClaim]:
    """Explicit existing-task hook: bounded expiry refresh then normal 109 claims.

    No timer/retry loop or source requests. Caller must commit before building a
    new cutoff/batch. A consumer key identifies one configured play/profile set.
    """
    _consumer(consumer_key)
    _match_filter(match_id)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("claim limit must be 1..32")
    if type(lease_seconds) is not int or not 10 <= lease_seconds <= 900:
        raise ValueError("lease_seconds must be 10..900")
    _read_transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            """WITH due AS MATERIALIZED (
                SELECT d.match_id,d.input_version FROM prediction_input_dirty_matches d
                JOIN official_matches m ON m.id=d.match_id
                WHERE (%(match)s::bigint IS NULL OR d.match_id=%(match)s)
                    AND lower(COALESCE(m.match_status,'')) IN ('scheduled','selling','not_started')
                    AND m.kickoff_time>timezone('Asia/Shanghai',clock_timestamp())
                    AND (%(research)s OR (m.sale_status='selling'
                        AND m.sale_stop_time>timezone('Asia/Shanghai',clock_timestamp())))
                    AND (EXISTS (SELECT 1 FROM prediction_input_revisions r
                        WHERE r.match_id=d.match_id AND r.input_version=d.input_version
                        AND r.consumer_key=%(consumer)s AND r.valid_until<=clock_timestamp())
                    OR EXISTS (SELECT 1 FROM prediction_input_consumptions c
                        WHERE c.match_id=d.match_id AND c.input_version=d.input_version
                        AND c.consumer_key=%(consumer)s
                        AND c.result_refs->>'outcome'='awaiting_verification'
                        AND c.completed_at+%(retry)s*INTERVAL '1 second'<=clock_timestamp()))
                ORDER BY d.changed_at,d.match_id LIMIT %(limit)s FOR UPDATE OF d SKIP LOCKED
            ) UPDATE prediction_input_dirty_matches d SET input_version=d.input_version+1,
                changed_at=clock_timestamp() FROM due WHERE d.match_id=due.match_id
                AND d.input_version=due.input_version""",
            dict(
                consumer=consumer_key,
                limit=limit,
                match=match_id,
                retry=_IDENTITY_RECHECK_SECONDS,
                research=consumer_key == MAHER_SHADOW_CONSUMER,
            ),
        )
    return claim_input_updates(
        conn, consumer_key=consumer_key, limit=limit, lease_seconds=lease_seconds, match_id=match_id
    )
