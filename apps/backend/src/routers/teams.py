"""Teams and feature-snapshot endpoints (Stage 3)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db

router = APIRouter(tags=["teams"])


@router.get("/api/teams")
def list_teams():
    """List known teams with alias counts and profiles."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id, t.team_code, t.team_name_cn, t.team_name_en,
                    t.country, t.short_name,
                    COUNT(ta.id) AS alias_count,
                    COUNT(tsp.id) AS profile_count
                FROM teams t
                LEFT JOIN team_aliases ta ON ta.team_id = t.id
                LEFT JOIN team_season_profiles tsp ON tsp.team_id = t.id
                GROUP BY t.id
                ORDER BY t.team_name_cn
                """
            )
            rows = cur.fetchall()
    return {
        "teams": [
            {
                "id": r[0],
                "team_code": r[1],
                "team_name_cn": r[2],
                "team_name_en": r[3],
                "country": r[4],
                "short_name": r[5],
                "alias_count": r[6],
                "profile_count": r[7],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/features/snapshots")
def list_feature_snapshots(
    match_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List recent feature snapshots, optionally filtered by match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if match_id:
                cur.execute(
                    """
                    SELECT fs.id, fs.match_id, fs.snapshot_time, fs.feature_version,
                           fs.home_team_id, fs.away_team_id,
                           fs.data_completeness_score, fs.uncertainty_score,
                           fs.home_rest_days, fs.away_rest_days, fs.rest_days_diff,
                           m.home_team_name, m.away_team_name, m.league_name
                    FROM match_feature_snapshots fs
                    JOIN official_matches m ON m.id = fs.match_id
                    WHERE fs.match_id = %s
                    ORDER BY fs.snapshot_time DESC LIMIT %s
                    """,
                    (match_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT fs.id, fs.match_id, fs.snapshot_time, fs.feature_version,
                           fs.home_team_id, fs.away_team_id,
                           fs.data_completeness_score, fs.uncertainty_score,
                           fs.home_rest_days, fs.away_rest_days, fs.rest_days_diff,
                           m.home_team_name, m.away_team_name, m.league_name
                    FROM match_feature_snapshots fs
                    JOIN official_matches m ON m.id = fs.match_id
                    ORDER BY fs.snapshot_time DESC LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return {
        "snapshots": [
            {
                "id": r[0],
                "match_id": r[1],
                "snapshot_time": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "feature_version": r[3],
                "home_team_id": r[4],
                "away_team_id": r[5],
                "data_completeness_score": float(r[6]) if r[6] else None,
                "uncertainty_score": float(r[7]) if r[7] else None,
                "home_rest_days": r[8],
                "away_rest_days": r[9],
                "rest_days_diff": r[10],
                "home_team_name": r[11],
                "away_team_name": r[12],
                "league_name": r[13],
            }
            for r in rows
        ],
        "total": len(rows),
    }
