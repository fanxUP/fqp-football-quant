"""Model predictions and simulation tickets endpoints (Stage 4)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db

router = APIRouter(tags=["predictions"])


@router.get("/api/predictions")
def list_predictions(
    match_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List recent model predictions, optionally filtered by match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if match_id:
                cur.execute(
                    """
                    SELECT mp.id, mp.match_id, mp.predict_time,
                           mv.model_name, mp.play_type, mp.option_code,
                           mp.model_probability, mp.market_probability,
                           mp.fair_odds, mp.ev, mp.confidence_score,
                           m.home_team_name, m.away_team_name
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    WHERE mp.match_id = %s
                    ORDER BY mp.predict_time DESC, mp.ev DESC
                    LIMIT %s
                    """,
                    (match_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT mp.id, mp.match_id, mp.predict_time,
                           mv.model_name, mp.play_type, mp.option_code,
                           mp.model_probability, mp.market_probability,
                           mp.fair_odds, mp.ev, mp.confidence_score,
                           m.home_team_name, m.away_team_name
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    ORDER BY mp.predict_time DESC, mp.ev DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return {
        "predictions": [
            {
                "id": r[0],
                "match_id": r[1],
                "predict_time": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "model_name": r[3],
                "play_type": r[4],
                "option_code": r[5],
                "model_probability": float(r[6]) if r[6] else None,
                "market_probability": float(r[7]) if r[7] else None,
                "fair_odds": float(r[8]) if r[8] else None,
                "ev": float(r[9]) if r[9] else None,
                "confidence": float(r[10]) if r[10] else None,
                "home_team": r[11],
                "away_team": r[12],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/tickets")
def list_tickets(
    status: str | None = Query(None),
    limit: int = Query(20),
):
    """List simulation tickets, optionally filtered by status."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    SELECT st.id, st.strategy_pool, st.pass_type,
                           st.suggested_stake, st.estimated_return,
                           st.expected_value, st.risk_level, st.ticket_status,
                           st.created_at,
                           COUNT(sti.id) AS item_count
                    FROM simulation_tickets st
                    LEFT JOIN simulation_ticket_items sti ON sti.ticket_id = st.id
                    WHERE st.ticket_status = %s
                    GROUP BY st.id
                    ORDER BY st.created_at DESC LIMIT %s
                    """,
                    (status, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT st.id, st.strategy_pool, st.pass_type,
                           st.suggested_stake, st.estimated_return,
                           st.expected_value, st.risk_level, st.ticket_status,
                           st.created_at,
                           COUNT(sti.id) AS item_count
                    FROM simulation_tickets st
                    LEFT JOIN simulation_ticket_items sti ON sti.ticket_id = st.id
                    GROUP BY st.id
                    ORDER BY st.created_at DESC LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return {
        "tickets": [
            {
                "id": r[0],
                "strategy_pool": r[1],
                "pass_type": r[2],
                "suggested_stake": float(r[3]) if r[3] else 0,
                "estimated_return": float(r[4]) if r[4] else None,
                "expected_value": float(r[5]) if r[5] else None,
                "risk_level": r[6],
                "status": r[7],
                "created_at": r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8]),
                "item_count": r[9],
            }
            for r in rows
        ],
        "total": len(rows),
    }
