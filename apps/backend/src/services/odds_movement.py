"""Batch query service for date-indexed official odds movements."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
PlayType = Literal["spf", "rqspf", "bf", "zjq", "bqc"]
OddsScope = Literal["current", "history"]
Resolution = Literal["raw", "hour"]


def _business_iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=BUSINESS_TIMEZONE)
        else:
            value = value.astimezone(BUSINESS_TIMEZONE)
        return value.isoformat()
    return str(value)


def _movement_sql(scope: OddsScope, resolution: Resolution) -> str:
    if scope == "current":
        match_filter = """
            m.kickoff_time > timezone('Asia/Shanghai', NOW())
            AND m.sale_status = 'selling'
            AND EXISTS (
                SELECT 1 FROM official_markets market
                WHERE market.match_id = m.id
                  AND market.is_open = TRUE
                  AND market.play_type = ANY(%(canonical_play_types)s)
            )
        """
    else:
        match_filter = """
            m.business_date = %(business_date)s::date
            AND m.kickoff_time <= timezone('Asia/Shanghai', NOW())
            AND EXISTS (
                SELECT 1 FROM official_odds_snapshots history
                WHERE history.match_id = m.id
            )
        """

    if resolution == "hour":
        sampled_snapshots = """
            SELECT DISTINCT ON (
                snapshot.match_id, snapshot.play_type, snapshot.option_code,
                date_trunc('hour', snapshot.business_snapshot_time)
            ) snapshot.*
            FROM source_snapshots snapshot
            ORDER BY snapshot.match_id, snapshot.play_type, snapshot.option_code,
                     date_trunc('hour', snapshot.business_snapshot_time),
                     snapshot.business_snapshot_time DESC, snapshot.id DESC
        """
    else:
        sampled_snapshots = "SELECT snapshot.* FROM source_snapshots snapshot"

    return f"""
        WITH selected_matches AS (
            SELECT m.id, m.business_date, m.official_match_code, m.league_name,
                   m.home_team_name, m.away_team_name, m.kickoff_time
            FROM official_matches m
            WHERE {match_filter}
            ORDER BY m.kickoff_time, m.id
            LIMIT %(limit)s
        ),
        source_snapshots AS (
            SELECT snapshot.*,
                   CASE
                       WHEN snapshot.raw_json->>'_collector_timezone' = 'Asia/Shanghai'
                         OR snapshot.raw_json->>'source_endpoint' = 'getFixedBonusV1.qry'
                       THEN snapshot.snapshot_time
                       ELSE snapshot.snapshot_time + INTERVAL '8 hours'
                   END AS business_snapshot_time
            FROM official_odds_snapshots snapshot
            WHERE snapshot.match_id IN (SELECT id FROM selected_matches)
              AND snapshot.play_type = %(play_type)s
        ),
        sampled_snapshots AS (
            {sampled_snapshots}
        ),
        selected_snapshots AS (
            SELECT snapshot.*,
                   LAG(snapshot.sp_value) OVER (
                       PARTITION BY snapshot.match_id, snapshot.play_type, snapshot.option_code
                       ORDER BY snapshot.business_snapshot_time, snapshot.id
                   ) AS prev_sp_value
            FROM sampled_snapshots snapshot
        )
        SELECT snapshot.id, match.id, match.official_match_code, match.business_date,
               match.league_name, match.home_team_name, match.away_team_name,
               match.kickoff_time, snapshot.business_snapshot_time,
               snapshot.option_code, snapshot.option_name, snapshot.sp_value,
               snapshot.handicap,
               CASE WHEN snapshot.sp_value > 0 THEN 1.0 / snapshot.sp_value ELSE NULL END,
               snapshot.prev_sp_value,
               capture.status, capture.capture_kind, capture.failure_reason
        FROM selected_matches match
        LEFT JOIN selected_snapshots snapshot ON snapshot.match_id = match.id
        LEFT JOIN LATERAL (
            SELECT batch.status, batch.capture_kind, batch.failure_reason
            FROM official_odds_capture_batches batch
            WHERE batch.match_id = match.id
            ORDER BY batch.attempted_at DESC, batch.id DESC
            LIMIT 1
        ) capture ON TRUE
        ORDER BY match.kickoff_time, match.id,
                 snapshot.business_snapshot_time, snapshot.option_code, snapshot.id
    """


def list_odds_movements(
    *,
    scope: OddsScope,
    business_date: str | None,
    play_type: PlayType,
    resolution: Resolution,
    limit: int,
) -> dict:
    """Return all matches and selected-play series in a single bounded query."""
    params = {
        "business_date": business_date,
        "play_type": play_type,
        "canonical_play_types": ["spf", "rqspf", "bf", "zjq", "bqc"],
        "limit": limit,
    }
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(_movement_sql(scope, resolution), params)
        rows = cur.fetchall()

    matches: dict[int, dict] = {}
    for row in rows:
        match_id = int(row[1])
        match = matches.setdefault(
            match_id,
            {
                "id": match_id,
                "official_match_code": str(row[2]),
                "business_date": row[3].isoformat()
                if hasattr(row[3], "isoformat")
                else str(row[3]),
                "league_name": str(row[4]),
                "home_team_name": str(row[5]),
                "away_team_name": str(row[6]),
                "kickoff_time": _business_iso(row[7]),
                "capture_status": {
                    "status": row[15],
                    "capture_kind": row[16],
                    "failure_reason": row[17],
                }
                if row[15]
                else None,
                "series": [],
                "anomalies": [],
            },
        )
        if row[0] is None:
            continue

        sp_value = float(row[11])
        prev_sp_value = float(row[14]) if row[14] is not None else None
        point = {
            "snapshot_id": int(row[0]),
            "snapshot_time": _business_iso(row[8]),
            "play_type": play_type,
            "option_code": str(row[9]),
            "option_name": str(row[10]),
            "sp_value": sp_value,
            "handicap": float(row[12]) if row[12] is not None else None,
            "implied_probability": float(row[13]) if row[13] is not None else None,
            "prev_sp_value": prev_sp_value,
        }
        match["series"].append(point)
        if prev_sp_value and (sp_value / prev_sp_value > 3 or sp_value / prev_sp_value < 0.33):
            match["anomalies"].append(
                {
                    "time": point["snapshot_time"],
                    "option_name": point["option_name"],
                    "sp_value": sp_value,
                    "prev_sp_value": prev_sp_value,
                    "ratio": round(sp_value / prev_sp_value, 2),
                    "type": "jump" if sp_value > prev_sp_value else "drop",
                }
            )

    return {
        "scope": scope,
        "business_date": business_date,
        "play_type": play_type,
        "resolution": resolution,
        "matches": list(matches.values()),
        "total": len(matches),
    }
