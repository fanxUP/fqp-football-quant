"""Official match and odds endpoints documented under /api/v1/official."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db

router = APIRouter(tags=["official"])


def _to_iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.get("/api/official/matches")
def list_official_matches(date: str = Query(...)):
    """List official matches by business date."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, official_match_code, league_name, home_team_name, away_team_name,
                       kickoff_time, match_status, raw_json->>'matchId' AS sporttery_match_id
                FROM official_matches
                WHERE business_date = %s::date
                ORDER BY kickoff_time, official_match_code
                """,
                (date,),
            )
            rows = cur.fetchall()
    return {
        "matches": [
            {
                "id": row[0],
                "official_match_code": row[1],
                "league_name": row[2],
                "home_team_name": row[3],
                "away_team_name": row[4],
                "kickoff_time": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
                "match_status": row[6],
                "sporttery_match_id": row[7],
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/api/official/matches/{match_id}")
def get_official_match(match_id: int):
    """Get one official match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, official_match_code, league_name, home_team_name, away_team_name,
                       kickoff_time, match_status, raw_json->>'matchId' AS sporttery_match_id, raw_json
                FROM official_matches
                WHERE id = %s
                """,
                (match_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"status": "not_found", "match_id": match_id}
    return {
        "id": row[0],
        "official_match_code": row[1],
        "league_name": row[2],
        "home_team_name": row[3],
        "away_team_name": row[4],
        "kickoff_time": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
        "match_status": row[6],
        "sporttery_match_id": row[7],
        "raw_json": row[8],
    }


@router.get("/api/official/matches/{match_id}/odds-snapshots")
def list_official_odds_snapshots(match_id: int, limit: int = Query(200)):
    """List append-only official odds snapshots for one match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, match_id, play_type, option_code, sp_value, handicap,
                       snapshot_time, is_open, is_single_allowed
                FROM official_odds_snapshots
                WHERE match_id = %s
                ORDER BY snapshot_time DESC, play_type, option_code
                LIMIT %s
                """,
                (match_id, limit),
            )
            rows = cur.fetchall()
    return {
        "snapshots": [
            {
                "id": row[0],
                "match_id": row[1],
                "play_type": row[2],
                "option_code": row[3],
                "sp_value": float(row[4]) if row[4] is not None else None,
                "handicap": float(row[5]) if row[5] is not None else None,
                "snapshot_time": row[6].isoformat()
                if hasattr(row[6], "isoformat")
                else str(row[6]),
                "is_open": row[7],
                "is_single_allowed": row[8],
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/api/official/collection-status")
def list_official_collection_status(
    business_date: str | None = Query(None),
    status: str | None = Query(None),
    source_name: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List official collection attempts and known source gaps."""
    filters = []
    params: dict[str, object] = {"limit": limit}
    if business_date:
        filters.append("business_date = %(business_date)s::date")
        params["business_date"] = business_date
    if status:
        filters.append("status = %(status)s")
        params["status"] = status
    if source_name:
        filters.append("source_name = %(source_name)s")
        params["source_name"] = source_name

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, business_date, crawl_type, source_name, status,
                       source_url, source_artifact_path, source_artifact_hash,
                       records_found, records_inserted, records_updated,
                       error_message, updated_at
                FROM official_collection_status
                {where_clause}
                ORDER BY business_date DESC, updated_at DESC, id DESC
                LIMIT %(limit)s
                """,
                params,
            )
            rows = cur.fetchall()

    return {
        "items": [
            {
                "id": row[0],
                "business_date": _to_iso(row[1]),
                "crawl_type": row[2],
                "source_name": row[3],
                "status": row[4],
                "source_url": row[5],
                "source_artifact_path": row[6],
                "source_artifact_hash": row[7],
                "records_found": row[8],
                "records_inserted": row[9],
                "records_updated": row[10],
                "error_message": row[11],
                "updated_at": _to_iso(row[12]),
            }
            for row in rows
        ],
        "total": len(rows),
    }
