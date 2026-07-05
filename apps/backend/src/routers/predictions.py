"""Model predictions and simulation tickets endpoints (Stage 4)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db

router = APIRouter(tags=["predictions"])

# Play type display names
PLAY_TYPE_NAMES: dict[str, str] = {
    "spf": "胜平负",
    "rqspf": "让球胜平负",
    "zjq": "总进球数",
    "bf": "比分",
    "bqc": "半全场",
    # Legacy aliases
    "total_goals": "总进球数",
    "score": "比分",
    "half_full": "半全场",
}

OPTION_NAMES: dict[str, str] = {
    "3": "主胜",
    "1": "平局",
    "0": "客胜",
}

RQSPF_OPTION_NAMES: dict[str, str] = {
    "3": "让胜",
    "1": "让平",
    "0": "让负",
}

# BQC semi-full mapping
BQC_HT = {"3": "胜", "1": "平", "0": "负"}
BQC_FT = {"3": "胜", "1": "平", "0": "负"}


def _option_name(play_type: str, option_code: str, handicap: float | None = None) -> str:
    """Get option display name, respecting play type and handicap."""
    if play_type == "rqspf":
        name = RQSPF_OPTION_NAMES.get(option_code, option_code)
    elif play_type == "bqc" and len(option_code) == 2:
        name = f"{BQC_HT.get(option_code[0], option_code[0])}{BQC_FT.get(option_code[1], option_code[1])}"
    elif play_type == "bf":
        name = option_code  # e.g. "1:0", "2:1"
    elif play_type == "zjq":
        name = f"{option_code}球" if option_code != "7" else "7+球"
    else:
        name = OPTION_NAMES.get(option_code, option_code)
    if handicap is not None:
        name = f"{name}({handicap:+g})"
    return name


@router.get("/api/recommendations/live")
def get_live_recommendations(
    limit: int = Query(20),
    min_ev: float = Query(0.02, description="最小EV阈值"),
    min_confidence: float = Query(0.3, description="最小置信度"),
):
    """Generate live betting recommendations from latest model predictions.

    Returns the best match+option combos with positive EV, sorted by EV descending.
    Each recommendation includes match info, odds, probabilities, edge, and suggested action.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (mp.match_id, mp.play_type, mp.option_code)
                        mp.id,
                        mp.match_id,
                        mp.play_type,
                        mp.option_code,
                        mp.model_probability,
                        mp.market_probability,
                        mp.fair_odds,
                        mp.ev,
                        mp.confidence_score,
                        mp.predict_time,
                        mv.model_name,
                        m.home_team_name,
                        m.away_team_name,
                        m.league_name,
                        m.kickoff_time,
                        m.match_status,
                        om.handicap
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    LEFT JOIN LATERAL (
                        SELECT handicap FROM official_odds_snapshots
                        WHERE match_id = mp.match_id AND play_type = mp.play_type
                          AND handicap IS NOT NULL
                        ORDER BY snapshot_time DESC LIMIT 1
                    ) om ON true
                    WHERE mp.ev > %(min_ev)s
                      AND mp.confidence_score >= %(min_confidence)s
                      AND m.match_status NOT IN ('Settled', 'Cancelled')
                    ORDER BY mp.match_id, mp.play_type, mp.option_code, mp.predict_time DESC
                )
                SELECT *
                FROM latest
                ORDER BY ev DESC, confidence_score DESC
                LIMIT %(limit)s
                """,
                {"min_ev": min_ev, "min_confidence": min_confidence, "limit": limit},
            )
            rows = cur.fetchall()

    recommendations = []
    for r in rows:
        model_prob = float(r[4]) if r[4] else 0
        market_prob = float(r[5]) if r[5] else 0
        fair_odds = float(r[6]) if r[6] else 0
        ev = float(r[7]) if r[7] else 0
        confidence = float(r[8]) if r[8] else 0
        edge = model_prob - market_prob if market_prob > 0 else 0
        handicap = float(r[16]) if len(r) > 16 and r[16] is not None else None

        recommendations.append({
            "prediction_id": r[0],
            "match_id": r[1],
            "play_type": r[2],
            "play_type_name": PLAY_TYPE_NAMES.get(r[2], r[2]),
            "option_code": r[3],
            "option_name": _option_name(r[2], r[3], handicap),
            "model_probability": round(model_prob, 4),
            "market_probability": round(market_prob, 4),
            "fair_odds": round(fair_odds, 2),
            "ev": round(ev, 4),
            "edge": round(edge, 4),
            "confidence": round(confidence, 4),
            "predict_time": r[9].isoformat() if hasattr(r[9], "isoformat") else str(r[9]),
            "model_name": r[10],
            "home_team": r[11],
            "away_team": r[12],
            "league": r[13],
            "kickoff_time": r[14].isoformat() if hasattr(r[14], "isoformat") else str(r[14]) if r[14] else None,
            "match_status": r[15],
        })

    return {"status": "ok", "recommendations": recommendations, "total": len(recommendations)}


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
