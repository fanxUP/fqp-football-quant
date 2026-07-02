"""Official data storage layer.

CRUD operations for the 6 official tables defined in 01_core_official_schema.sql.
Uses psycopg2 directly — no ORM. Every row stores raw_json + raw_hash.

Key rules:
  - Odds snapshots: INSERT only (append-only, never overwrite).
  - Matches/markets/results: upsert via ON CONFLICT.
  - Every function accepts a connection (from db.get_db()) and normalized dicts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_raw(raw: Any) -> str:
    """MD5 hash of JSON-serialized raw data."""
    return hashlib.md5(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# official_matches
# ---------------------------------------------------------------------------


def store_matches(conn: Any, matches: list[dict]) -> dict[str, Any]:
    """Insert or update matches in official_matches.

    Each match dict must have:
      business_date, official_match_code, league_name,
      home_team_name, away_team_name, kickoff_time

    Unique key: (business_date, official_match_code)
    """
    inserted, updated, errors = 0, 0, []
    sql = """
        INSERT INTO official_matches (
            sport_type, business_date, official_match_code, league_name,
            home_team_name, away_team_name, kickoff_time, sale_stop_time,
            sale_status, match_status, source_url, raw_hash, raw_json, updated_at
        ) VALUES (
            %(sport_type)s, %(business_date)s, %(official_match_code)s, %(league_name)s,
            %(home_team_name)s, %(away_team_name)s, %(kickoff_time)s, %(sale_stop_time)s,
            %(sale_status)s, %(match_status)s, %(source_url)s, %(raw_hash)s, %(raw_json)s, now()
        )
        ON CONFLICT (business_date, official_match_code) DO UPDATE SET
            league_name = EXCLUDED.league_name,
            home_team_name = EXCLUDED.home_team_name,
            away_team_name = EXCLUDED.away_team_name,
            kickoff_time = EXCLUDED.kickoff_time,
            sale_stop_time = EXCLUDED.sale_stop_time,
            sale_status = EXCLUDED.sale_status,
            match_status = EXCLUDED.match_status,
            source_url = EXCLUDED.source_url,
            raw_hash = EXCLUDED.raw_hash,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        RETURNING id, (xmax = 0) AS is_inserted
    """
    with conn.cursor() as cur:
        for m in matches:
            try:
                raw = m.get("raw_json", {})
                cur.execute(
                    sql,
                    {
                        "sport_type": m.get("sport_type", "football"),
                        "business_date": m["business_date"],
                        "official_match_code": m["official_match_code"],
                        "league_name": m["league_name"],
                        "home_team_name": m["home_team_name"],
                        "away_team_name": m["away_team_name"],
                        "kickoff_time": m.get("kickoff_time"),
                        "sale_stop_time": m.get("sale_stop_time"),
                        "sale_status": m.get("sale_status", "unknown"),
                        "match_status": m.get("match_status", "scheduled"),
                        "source_url": m.get("source_url", ""),
                        "raw_hash": _hash_raw(raw),
                        "raw_json": json.dumps(raw, ensure_ascii=False),
                    },
                )
                row = cur.fetchone()
                if row and row[1]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append({"match_code": m.get("official_match_code"), "error": str(e)})
    conn.commit()
    return {"inserted": inserted, "updated": updated, "errors": errors}


# ---------------------------------------------------------------------------
# official_markets
# ---------------------------------------------------------------------------


def store_markets(conn: Any, match_id: int, markets: list[dict]) -> dict[str, Any]:
    """Insert or update markets for a match.

    Each market dict must have: play_type.
    Optional: handicap, is_open, is_single_allowed, market_status.

    Unique key: (match_id, play_type, COALESCE(handicap, 9999))
    """
    inserted, updated, errors = 0, 0, []
    sql = """
        INSERT INTO official_markets (
            match_id, play_type, handicap, is_open, is_single_allowed,
            market_status, raw_json, updated_at
        ) VALUES (
            %(match_id)s, %(play_type)s, %(handicap)s, %(is_open)s, %(is_single_allowed)s,
            %(market_status)s, %(raw_json)s, now()
        )
        ON CONFLICT (match_id, play_type, COALESCE(handicap, 9999)) DO UPDATE SET
            is_open = EXCLUDED.is_open,
            is_single_allowed = EXCLUDED.is_single_allowed,
            market_status = EXCLUDED.market_status,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        RETURNING id, (xmax = 0) AS is_inserted
    """
    with conn.cursor() as cur:
        for mkt in markets:
            try:
                raw = mkt.get("raw_json", {})
                cur.execute(
                    sql,
                    {
                        "match_id": match_id,
                        "play_type": mkt["play_type"],
                        "handicap": mkt.get("handicap"),
                        "is_open": mkt.get("is_open", True),
                        "is_single_allowed": mkt.get("is_single_allowed", False),
                        "market_status": mkt.get("market_status", "open"),
                        "raw_json": json.dumps(raw, ensure_ascii=False),
                    },
                )
                row = cur.fetchone()
                if row and row[1]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append({"play_type": mkt.get("play_type"), "error": str(e)})
    conn.commit()
    return {"inserted": inserted, "updated": updated, "errors": errors}


# ---------------------------------------------------------------------------
# official_odds_snapshots (append-only)
# ---------------------------------------------------------------------------


def store_odds_snapshots(
    conn: Any,
    match_id: int,
    market_id: int | None,
    snapshots: list[dict],
) -> dict[str, Any]:
    """Insert odds snapshots (append-only, never overwrite).

    Each snapshot dict must have:
      play_type, option_code, option_name, sp_value, snapshot_time
    """
    inserted, errors = 0, []
    sql = """
        INSERT INTO official_odds_snapshots (
            match_id, market_id, snapshot_time, snapshot_label,
            minutes_before_stop, play_type, option_code, option_name,
            sp_value, handicap, is_open, is_single_allowed,
            raw_json, raw_hash, created_at
        ) VALUES (
            %(match_id)s, %(market_id)s, %(snapshot_time)s, %(snapshot_label)s,
            %(minutes_before_stop)s, %(play_type)s, %(option_code)s, %(option_name)s,
            %(sp_value)s, %(handicap)s, %(is_open)s, %(is_single_allowed)s,
            %(raw_json)s, %(raw_hash)s, now()
        )
    """
    with conn.cursor() as cur:
        for snap in snapshots:
            try:
                raw = snap.get("raw_json", {})
                cur.execute(
                    sql,
                    {
                        "match_id": match_id,
                        "market_id": market_id,
                        "snapshot_time": snap["snapshot_time"],
                        "snapshot_label": snap.get("snapshot_label"),
                        "minutes_before_stop": snap.get("minutes_before_stop"),
                        "play_type": snap["play_type"],
                        "option_code": snap["option_code"],
                        "option_name": snap["option_name"],
                        "sp_value": snap["sp_value"],
                        "handicap": snap.get("handicap"),
                        "is_open": snap.get("is_open", True),
                        "is_single_allowed": snap.get("is_single_allowed", False),
                        "raw_json": json.dumps(raw, ensure_ascii=False),
                        "raw_hash": _hash_raw(raw),
                    },
                )
                inserted += 1
            except Exception as e:
                errors.append({"option_code": snap.get("option_code"), "error": str(e)})
    conn.commit()
    return {"inserted": inserted, "errors": errors}


# ---------------------------------------------------------------------------
# official_results
# ---------------------------------------------------------------------------


def store_results(conn: Any, results: list[dict]) -> dict[str, Any]:
    """Insert or update match results.

    Each result dict must have: match_id
    Unique key: (match_id)
    """
    inserted, updated, errors = 0, 0, []
    sql = """
        INSERT INTO official_results (
            match_id, half_home_goals, half_away_goals,
            full_home_goals, full_away_goals,
            spf_result, rqspf_result, total_goals_result,
            score_result, half_full_result, result_status,
            official_publish_time, raw_json, updated_at
        ) VALUES (
            %(match_id)s, %(half_home_goals)s, %(half_away_goals)s,
            %(full_home_goals)s, %(full_away_goals)s,
            %(spf_result)s, %(rqspf_result)s, %(total_goals_result)s,
            %(score_result)s, %(half_full_result)s, %(result_status)s,
            %(official_publish_time)s, %(raw_json)s, now()
        )
        ON CONFLICT (match_id) DO UPDATE SET
            half_home_goals = EXCLUDED.half_home_goals,
            half_away_goals = EXCLUDED.half_away_goals,
            full_home_goals = EXCLUDED.full_home_goals,
            full_away_goals = EXCLUDED.full_away_goals,
            spf_result = EXCLUDED.spf_result,
            rqspf_result = EXCLUDED.rqspf_result,
            total_goals_result = EXCLUDED.total_goals_result,
            score_result = EXCLUDED.score_result,
            half_full_result = EXCLUDED.half_full_result,
            result_status = EXCLUDED.result_status,
            official_publish_time = EXCLUDED.official_publish_time,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        RETURNING id, (xmax = 0) AS is_inserted
    """
    with conn.cursor() as cur:
        for r in results:
            try:
                raw = r.get("raw_json", {})
                cur.execute(
                    sql,
                    {
                        "match_id": r["match_id"],
                        "half_home_goals": r.get("half_home_goals"),
                        "half_away_goals": r.get("half_away_goals"),
                        "full_home_goals": r.get("full_home_goals"),
                        "full_away_goals": r.get("full_away_goals"),
                        "spf_result": r.get("spf_result"),
                        "rqspf_result": r.get("rqspf_result"),
                        "total_goals_result": r.get("total_goals_result"),
                        "score_result": r.get("score_result"),
                        "half_full_result": r.get("half_full_result"),
                        "result_status": r.get("result_status", "pending"),
                        "official_publish_time": r.get("official_publish_time"),
                        "raw_json": json.dumps(raw, ensure_ascii=False),
                    },
                )
                row = cur.fetchone()
                if row and row[1]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append({"match_id": r.get("match_id"), "error": str(e)})
    conn.commit()
    return {"inserted": inserted, "updated": updated, "errors": errors}


# ---------------------------------------------------------------------------
# official_crawl_logs
# ---------------------------------------------------------------------------


def log_crawl(
    conn: Any,
    source_name: str,
    crawl_type: str,
    status: str,
    records_found: int = 0,
    records_inserted: int = 0,
    records_updated: int = 0,
    error_message: str | None = None,
    raw_response_hash: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int:
    """Insert a crawl log row. Returns the new row id."""
    sql = """
        INSERT INTO official_crawl_logs (
            source_name, crawl_type, started_at, finished_at,
            status, records_found, records_inserted, records_updated,
            error_message, raw_response_hash, created_at
        ) VALUES (
            %(source_name)s, %(crawl_type)s, %(started_at)s, %(finished_at)s,
            %(status)s, %(records_found)s, %(records_inserted)s, %(records_updated)s,
            %(error_message)s, %(raw_response_hash)s, now()
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "source_name": source_name,
                "crawl_type": crawl_type,
                "started_at": started_at or _now(),
                "finished_at": finished_at or _now(),
                "status": status,
                "records_found": records_found,
                "records_inserted": records_inserted,
                "records_updated": records_updated,
                "error_message": error_message,
                "raw_response_hash": raw_response_hash,
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else -1


# ---------------------------------------------------------------------------
# data_source_health
# ---------------------------------------------------------------------------


def update_health(
    conn: Any,
    source_name: str,
    source_type: str,
    status: str,
    latency_ms: int = 0,
    error_message: str | None = None,
) -> None:
    """Update or insert a data source health record.

    Uses SELECT-then-UPSERT because the table has no UNIQUE constraint
    on (source_name, source_type) — we match by those columns manually.
    """
    now_ts = _now()
    with conn.cursor() as cur:
        # Try to find existing row
        cur.execute(
            "SELECT id, failure_count FROM data_source_health "
            "WHERE source_name = %s AND source_type = %s "
            "ORDER BY id DESC LIMIT 1",
            (source_name, source_type),
        )
        row = cur.fetchone()
        if row:
            health_id, prev_failures = row
            cur.execute(
                """
                UPDATE data_source_health SET
                    status = %(status)s,
                    last_success_time = %(last_success)s,
                    last_failure_time = %(last_failure)s,
                    failure_count = failure_count + %(failure_count)s,
                    latency_ms = %(latency_ms)s,
                    error_message = %(error_message)s
                WHERE id = %(id)s
                """,
                {
                    "status": status,
                    "last_success": now_ts if status == "ok" else None,
                    "last_failure": now_ts if status != "ok" else None,
                    "failure_count": 0 if status == "ok" else 1,
                    "latency_ms": latency_ms,
                    "error_message": error_message,
                    "id": health_id,
                },
            )
        else:
            cur.execute(
                """
                INSERT INTO data_source_health (
                    source_name, source_type, status,
                    last_success_time, last_failure_time,
                    failure_count, latency_ms, error_message, created_at
                ) VALUES (
                    %(source_name)s, %(source_type)s, %(status)s,
                    %(last_success)s, %(last_failure)s,
                    %(failure_count)s, %(latency_ms)s, %(error_message)s, now()
                )
                """,
                {
                    "source_name": source_name,
                    "source_type": source_type,
                    "status": status,
                    "last_success": now_ts if status == "ok" else None,
                    "last_failure": now_ts if status != "ok" else None,
                    "failure_count": 0 if status == "ok" else 1,
                    "latency_ms": latency_ms,
                    "error_message": error_message,
                },
            )
    conn.commit()
