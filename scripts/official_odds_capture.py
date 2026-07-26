"""Durable dispatcher for official opening, periodic and kickoff odds captures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.odds_capture_policy import (
    BUSINESS_TIMEZONE,
    FINAL_CAPTURE_GRACE,
    CaptureCandidate,
    capture_decision,
    evaluate_capture_completeness,
)
from scripts.official_crawler import (
    parse_matches_from_response,
    parse_odds_snapshots_from_match,
)
from scripts.official_storage import log_crawl, store_markets, store_odds_snapshots, update_health
from scripts.sporttery_client import SportteryClient


@dataclass(frozen=True)
class OfficialCaptureCandidate(CaptureCandidate):
    business_date: date
    official_match_code: str
    expected_play_types: tuple[str, ...]


def _close_expired_sales(conn: Any, now: datetime) -> int:
    """Close local sales after the final-capture grace window expires."""
    local_now = now.astimezone(BUSINESS_TIMEZONE).replace(tzinfo=None)
    expiry_cutoff = local_now - FINAL_CAPTURE_GRACE
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE official_matches
               SET sale_status = 'closed', updated_at = NOW()
               WHERE sale_status = 'selling' AND kickoff_time < %s""",
            (expiry_cutoff,),
        )
        changed = cur.rowcount
    conn.commit()
    return max(0, int(changed))


def _load_candidates(conn: Any, now: datetime) -> list[OfficialCaptureCandidate]:
    """Load sellable future matches plus recently started final-capture matches."""
    local_now = now.astimezone(BUSINESS_TIMEZONE).replace(tzinfo=None)
    grace_start = local_now - FINAL_CAPTURE_GRACE
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH relevant_matches AS MATERIALIZED (
                SELECT m.id, m.business_date, m.official_match_code, m.kickoff_time
                FROM official_matches m
                WHERE m.kickoff_time >= %(grace_start)s
                  AND (
                      (m.kickoff_time > %(now)s AND m.sale_status = 'selling')
                      OR
                      (m.kickoff_time <= %(now)s AND EXISTS (
                          SELECT 1
                          FROM official_odds_snapshots history
                          WHERE history.match_id = m.id
                      ))
                  )
            ),
            offered_plays AS (
                SELECT offered.match_id,
                       ARRAY_AGG(DISTINCT offered.play_type ORDER BY offered.play_type)
                           AS play_types
                FROM (
                    SELECT market.match_id, market.play_type
                    FROM official_markets market
                    JOIN relevant_matches relevant ON relevant.id = market.match_id
                    WHERE market.play_type = ANY(%(canonical_play_types)s)
                      AND market.is_open = TRUE
                    UNION
                    SELECT history.match_id, history.play_type
                    FROM official_odds_snapshots history
                    JOIN relevant_matches relevant ON relevant.id = history.match_id
                    WHERE history.play_type = ANY(%(canonical_play_types)s)
                ) offered
                GROUP BY offered.match_id
            )
            SELECT relevant.id, relevant.business_date, relevant.official_match_code,
                   relevant.kickoff_time,
                   offered.play_types,
                   latest.attempted_at, latest.status,
                   EXISTS (
                       SELECT 1 FROM official_odds_capture_batches final_batch
                       WHERE final_batch.match_id = relevant.id
                         AND final_batch.capture_kind = 'final'
                   ) AS final_attempted
            FROM relevant_matches relevant
            JOIN offered_plays offered ON offered.match_id = relevant.id
            LEFT JOIN LATERAL (
                SELECT attempted_at, status
                FROM official_odds_capture_batches batch
                WHERE batch.match_id = relevant.id AND batch.capture_kind <> 'final'
                ORDER BY attempted_at DESC, id DESC
                LIMIT 1
            ) latest ON TRUE
            ORDER BY relevant.kickoff_time, relevant.id
            """,
            {
                "canonical_play_types": ["spf", "rqspf", "bf", "zjq", "bqc"],
                "grace_start": grace_start,
                "now": local_now,
            },
        )
        rows = cur.fetchall()

    return [
        OfficialCaptureCandidate(
            match_id=int(row[0]),
            business_date=row[1],
            official_match_code=str(row[2]),
            kickoff_time=row[3],
            expected_play_types=tuple(row[4] or ()),
            last_attempt_at=row[5],
            last_attempt_status=str(row[6]) if row[6] else None,
            final_attempted=bool(row[7]),
        )
        for row in rows
    ]


def _reserve_batch(
    conn: Any,
    candidate: OfficialCaptureCandidate,
    capture_kind: str,
    scheduled_for: datetime,
) -> int | None:
    """Atomically reserve one capture so concurrent dispatchers cannot duplicate it."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO official_odds_capture_batches (
                match_id, scheduled_for, capture_kind, expected_play_types
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (match_id, scheduled_for, capture_kind) DO NOTHING
            RETURNING id
            """,
            (
                candidate.match_id,
                scheduled_for,
                capture_kind,
                list(candidate.expected_play_types),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else None


def _finish_batch(
    conn: Any,
    batch_id: int,
    status: str,
    captured_play_types: tuple[str, ...] = (),
    snapshot_count: int = 0,
    failure_reason: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE official_odds_capture_batches
            SET status = %s, captured_play_types = %s, snapshot_count = %s,
                failure_reason = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (status, list(captured_play_types), snapshot_count, failure_reason, batch_id),
        )
    conn.commit()


def collect_due_official_odds(now: datetime | None = None) -> dict[str, Any]:
    """Capture only due matches using one official calculator response."""
    current = now or datetime.now(BUSINESS_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BUSINESS_TIMEZONE)
    current = current.astimezone(BUSINESS_TIMEZONE)

    reserved: list[tuple[OfficialCaptureCandidate, str, int]] = []
    with get_db() as conn:
        _close_expired_sales(conn, current)
        for candidate in _load_candidates(conn, current):
            decision = capture_decision(candidate, current)
            if not decision.is_due or not decision.capture_kind or not decision.scheduled_for:
                continue
            scheduled_for = decision.scheduled_for.replace(second=0, microsecond=0)
            batch_id = _reserve_batch(conn, candidate, decision.capture_kind, scheduled_for)
            if batch_id is not None:
                reserved.append((candidate, decision.capture_kind, batch_id))
        if not reserved:
            update_health(conn, "sporttery", "odds", "ok", 0)

    if not reserved:
        return {"status": "ok", "matches_due": 0, "snapshots_inserted": 0}

    started_at = current.replace(tzinfo=None).isoformat(timespec="seconds")
    client = SportteryClient()
    try:
        raw = client.get_uniform_match_calculator()
        parsed = parse_matches_from_response(raw, current.date().isoformat())
        source_matches = {
            (str(match["business_date"]), str(match["official_match_code"])): match
            for match in parsed
        }
        snapshot_time = current.replace(tzinfo=None).isoformat(timespec="seconds")
        inserted_total = 0
        complete_count = 0

        with get_db() as conn:
            for candidate, capture_kind, batch_id in reserved:
                source_match = source_matches.get(
                    (candidate.business_date.isoformat(), candidate.official_match_code)
                )
                snapshots = (
                    parse_odds_snapshots_from_match(
                        source_match.get("raw_json", {}), snapshot_time=snapshot_time
                    )
                    if source_match
                    else []
                )
                snapshots = [
                    snapshot
                    for snapshot in snapshots
                    if snapshot.get("play_type") in candidate.expected_play_types
                ]
                for snapshot in snapshots:
                    snapshot["raw_json"] = {
                        **snapshot.get("raw_json", {}),
                        "_collector_timezone": "Asia/Shanghai",
                    }
                completeness = evaluate_capture_completeness(
                    candidate.expected_play_types, snapshots
                )
                inserted = 0
                if source_match:
                    store_markets(conn, candidate.match_id, source_match.get("_markets", []))
                if snapshots:
                    result = store_odds_snapshots(
                        conn,
                        match_id=candidate.match_id,
                        market_id=None,
                        snapshots=snapshots,
                    )
                    inserted = int(result.get("inserted", 0))

                status = completeness.status
                failure_reason = None
                if capture_kind == "final" and status != "complete":
                    status = "failed"
                    failure_reason = "开赛时官方赔率已关闭或不完整，最后成功快照作为封盘赔率"
                elif completeness.missing_play_types:
                    failure_reason = "缺少玩法: " + ",".join(completeness.missing_play_types)

                _finish_batch(
                    conn,
                    batch_id,
                    status,
                    completeness.captured_play_types,
                    inserted,
                    failure_reason,
                )
                inserted_total += inserted
                complete_count += int(status == "complete")

            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="odds_snapshot",
                status="ok" if complete_count == len(reserved) else "partial",
                records_found=len(reserved),
                records_inserted=inserted_total,
                started_at=started_at,
            )
            update_health(conn, "sporttery", "odds", "ok", 0)

        return {
            "status": "ok",
            "matches_due": len(reserved),
            "matches_complete": complete_count,
            "snapshots_inserted": inserted_total,
        }
    except Exception as exc:
        with get_db() as conn:
            for _, _, batch_id in reserved:
                _finish_batch(conn, batch_id, "failed", failure_reason=str(exc))
            update_health(conn, "sporttery", "odds", "error", 0, str(exc))
        return {"status": "error", "matches_due": len(reserved), "error": str(exc)}
    finally:
        client.close()
