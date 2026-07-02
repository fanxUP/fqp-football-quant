"""Enrichment data endpoints: injuries, lineups, weather, motivation, standings (Stage 3b)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.feature_storage import get_latest_standings as _get_std
from scripts.feature_storage import get_weather_for_match as _get_w

router = APIRouter(tags=["enrichment"])


@router.get("/api/enrichment/injuries")
def list_injuries(
    team_id: int | None = Query(None),
    match_id: int | None = Query(None),
    limit: int = Query(50),
):
    """List injury/availability data, optionally filtered by team or match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if team_id:
                cur.execute(
                    """
                    SELECT pas.player_id, pas.team_id, pas.availability_status,
                           pas.injury_type, pas.expected_return_date,
                           pas.absence_impact_score, pas.source_name,
                           p.player_name_en, p.primary_position
                    FROM player_availability_snapshots pas
                    LEFT JOIN players p ON p.id = pas.player_id
                    WHERE pas.team_id = %s
                      AND pas.availability_status IN ('injured', 'suspended', 'doubtful')
                    ORDER BY pas.snapshot_time DESC
                    LIMIT %s
                    """,
                    (team_id, limit),
                )
            elif match_id:
                cur.execute(
                    """
                    SELECT pas.player_id, pas.team_id, pas.availability_status,
                           pas.injury_type, pas.expected_return_date,
                           pas.absence_impact_score, pas.source_name,
                           p.player_name_en, p.primary_position
                    FROM player_availability_snapshots pas
                    LEFT JOIN players p ON p.id = pas.player_id
                    WHERE pas.match_id = %s
                    ORDER BY pas.absence_impact_score DESC
                    LIMIT %s
                    """,
                    (match_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT pas.player_id, pas.team_id, pas.availability_status,
                           pas.injury_type, pas.expected_return_date,
                           pas.absence_impact_score, pas.source_name,
                           p.player_name_en, p.primary_position
                    FROM player_availability_snapshots pas
                    LEFT JOIN players p ON p.id = pas.player_id
                    WHERE pas.availability_status IN ('injured', 'suspended', 'doubtful')
                    ORDER BY pas.snapshot_time DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    return {
        "injuries": [
            {
                "player_id": r[0],
                "team_id": r[1],
                "status": r[2],
                "injury_type": r[3],
                "expected_return": str(r[4]) if r[4] else None,
                "impact_score": float(r[5]) if r[5] else None,
                "source": r[6],
                "player_name": r[7],
                "position": r[8],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/enrichment/lineups")
def list_lineups(
    match_id: int | None = Query(None),
    team_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List lineup snapshots, optionally filtered by match or team."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if match_id:
                cur.execute(
                    """
                    SELECT mls.id, mls.match_id, mls.team_id, mls.lineup_type,
                           mls.formation, mls.lineup_strength_score,
                           mls.rotation_risk_score, mls.starting_11_market_value,
                           mls.starting_11_key_player_count, mls.snapshot_time
                    FROM match_lineup_snapshots mls
                    WHERE mls.match_id = %s
                    ORDER BY mls.snapshot_time DESC
                    LIMIT %s
                    """,
                    (match_id, limit),
                )
            elif team_id:
                cur.execute(
                    """
                    SELECT mls.id, mls.match_id, mls.team_id, mls.lineup_type,
                           mls.formation, mls.lineup_strength_score,
                           mls.rotation_risk_score, mls.starting_11_market_value,
                           mls.starting_11_key_player_count, mls.snapshot_time
                    FROM match_lineup_snapshots mls
                    WHERE mls.team_id = %s
                    ORDER BY mls.snapshot_time DESC
                    LIMIT %s
                    """,
                    (team_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT mls.id, mls.match_id, mls.team_id, mls.lineup_type,
                           mls.formation, mls.lineup_strength_score,
                           mls.rotation_risk_score, mls.starting_11_market_value,
                           mls.starting_11_key_player_count, mls.snapshot_time
                    FROM match_lineup_snapshots mls
                    ORDER BY mls.snapshot_time DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    return {
        "lineups": [
            {
                "id": r[0],
                "match_id": r[1],
                "team_id": r[2],
                "lineup_type": r[3],
                "formation": r[4],
                "strength_score": float(r[5]) if r[5] else None,
                "rotation_risk": float(r[6]) if r[6] else None,
                "starting_11_value": float(r[7]) if r[7] else None,
                "key_player_count": r[8],
                "snapshot_time": str(r[9]),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/enrichment/weather")
def list_weather(
    match_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List weather snapshots, optionally filtered by match."""
    with get_db() as conn:
        if match_id:
            w = _get_w(conn, match_id)
            data = [w] if w else []
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT match_id, temperature_2m, precipitation, wind_speed_10m,
                           weather_impact_score, goal_expectation_adjustment,
                           snapshot_time, source_name
                    FROM match_weather_snapshots
                    ORDER BY snapshot_time DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            data = [
                {
                    "match_id": r[0],
                    "temperature_2m": float(r[1]) if r[1] else None,
                    "precipitation": float(r[2]) if r[2] else None,
                    "wind_speed_10m": float(r[3]) if r[3] else None,
                    "weather_impact": float(r[4]) if r[4] else None,
                    "goal_expectation_adj": float(r[5]) if r[5] else None,
                    "snapshot_time": str(r[6]),
                    "source": r[7],
                }
                for r in rows
            ]

    return {"weather": data, "total": len(data)}


@router.get("/api/enrichment/motivation")
def list_motivation(
    match_id: int | None = Query(None),
    team_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List motivation snapshots, optionally filtered by match or team."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if match_id:
                cur.execute(
                    """
                    SELECT tms.match_id, tms.team_id, tms.final_motivation_score,
                           tms.must_win, tms.draw_enough, tms.already_qualified,
                           tms.already_eliminated, tms.snapshot_time
                    FROM team_motivation_snapshots tms
                    WHERE tms.match_id = %s
                    ORDER BY tms.team_id
                    LIMIT %s
                    """,
                    (match_id, limit),
                )
            elif team_id:
                cur.execute(
                    """
                    SELECT tms.match_id, tms.team_id, tms.final_motivation_score,
                           tms.must_win, tms.draw_enough, tms.already_qualified,
                           tms.already_eliminated, tms.snapshot_time
                    FROM team_motivation_snapshots tms
                    WHERE tms.team_id = %s
                    ORDER BY tms.snapshot_time DESC
                    LIMIT %s
                    """,
                    (team_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT tms.match_id, tms.team_id, tms.final_motivation_score,
                           tms.must_win, tms.draw_enough, tms.already_qualified,
                           tms.already_eliminated, tms.snapshot_time
                    FROM team_motivation_snapshots tms
                    ORDER BY tms.snapshot_time DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    return {
        "motivation": [
            {
                "match_id": r[0],
                "team_id": r[1],
                "motivation_score": float(r[2]) if r[2] else None,
                "must_win": r[3],
                "draw_enough": r[4],
                "already_qualified": r[5],
                "already_eliminated": r[6],
                "snapshot_time": str(r[7]),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/enrichment/standings")
def list_standings(
    competition_id: int | None = Query(None),
    limit: int = Query(30),
):
    """Get the latest league standings for a competition."""
    if not competition_id:
        return {"standings": [], "total": 0, "note": "competition_id required"}

    with get_db() as conn:
        standings = _get_std(conn, competition_id)

    return {"standings": standings, "total": len(standings)}
