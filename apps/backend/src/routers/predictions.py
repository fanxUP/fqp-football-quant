"""Model predictions and simulation tickets endpoints (Stage 4)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.sporttery_sales import get_sporttery_sales_window

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
    sales_window = get_sporttery_sales_window()
    if not sales_window.is_open:
        return {
            "status": "resting",
            "recommendations": [],
            "total": 0,
            "sales_window": sales_window.as_dict(),
        }

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest_by_model AS (
                    SELECT DISTINCT ON (mp.match_id, mp.model_version_id, mp.play_type, mp.option_code)
                        mp.id,
                        mp.match_id,
                        mp.model_version_id,
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
                        m.official_match_code,
                        r.half_home_goals,
                        r.half_away_goals,
                        r.full_home_goals,
                        r.full_away_goals,
                        (r.raw_json->>'et_home_goals')::int AS et_home_goals,
                        (r.raw_json->>'et_away_goals')::int AS et_away_goals,
                        (r.raw_json->>'pk_home_goals')::int AS pk_home_goals,
                        (r.raw_json->>'pk_away_goals')::int AS pk_away_goals,
                        r.spf_result,
                        r.rqspf_result,
                        r.total_goals_result,
                        r.score_result,
                        r.half_full_result
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    LEFT JOIN official_results r ON r.match_id = m.id
                    WHERE mv.is_active = true
                      AND mp.odds_snapshot_id IS NOT NULL
                      AND mp.feature_snapshot_id IS NOT NULL
                      AND m.sale_status = 'selling'
                      AND LOWER(COALESCE(m.match_status, '')) IN ('scheduled', 'selling', 'not_started')
                      AND m.kickoff_time > timezone('Asia/Shanghai', NOW())
                      AND mp.predict_time < m.kickoff_time
                      AND (m.sale_stop_time IS NULL OR m.sale_stop_time > timezone('Asia/Shanghai', NOW()))
                      AND EXISTS (
                          SELECT 1
                          FROM official_markets market
                          WHERE market.match_id = m.id
                            AND market.play_type = mp.play_type
                            AND market.is_open = true
                      )
                    ORDER BY mp.match_id, mp.model_version_id, mp.play_type,
                             mp.option_code, mp.predict_time DESC, mp.id DESC
                ), best_by_option AS (
                    SELECT DISTINCT ON (match_id, play_type, option_code) *
                    FROM latest_by_model
                    WHERE ev > %(min_ev)s
                      AND confidence_score >= %(min_confidence)s
                    ORDER BY match_id, play_type, option_code,
                             ev DESC NULLS LAST, confidence_score DESC NULLS LAST,
                             predict_time DESC, id DESC
                )
                SELECT id, match_id, play_type, option_code,
                       model_probability, market_probability, fair_odds, ev,
                       confidence_score, predict_time, model_name,
                       home_team_name, away_team_name, league_name,
                       kickoff_time, match_status, om.handicap,
                       official_match_code,
                       half_home_goals, half_away_goals,
                       full_home_goals, full_away_goals,
                       et_home_goals, et_away_goals,
                       pk_home_goals, pk_away_goals,
                       spf_result, rqspf_result, total_goals_result,
                       score_result, half_full_result
                FROM best_by_option
                LEFT JOIN LATERAL (
                    SELECT handicap FROM official_odds_snapshots
                    WHERE match_id = best_by_option.match_id
                      AND play_type = best_by_option.play_type
                      AND handicap IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1
                ) om ON true
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
        official_match_code = r[17] if len(r) > 17 else None
        ht_home_goals = r[18] if len(r) > 18 else None
        ht_away_goals = r[19] if len(r) > 19 else None
        ft_home_goals = r[20] if len(r) > 20 else None
        ft_away_goals = r[21] if len(r) > 21 else None
        et_home_goals = r[22] if len(r) > 22 else None
        et_away_goals = r[23] if len(r) > 23 else None
        pk_home_goals = r[24] if len(r) > 24 else None
        pk_away_goals = r[25] if len(r) > 25 else None
        spf_result = r[26] if len(r) > 26 else None
        rqspf_result = r[27] if len(r) > 27 else None
        total_goals_result = r[28] if len(r) > 28 else None
        score_result = r[29] if len(r) > 29 else None
        half_full_result = r[30] if len(r) > 30 else None

        recommendations.append(
            {
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
                "kickoff_time": r[14].isoformat()
                if hasattr(r[14], "isoformat")
                else str(r[14])
                if r[14]
                else None,
                "match_status": r[15],
                "match_num_str": official_match_code,
                "ht_home_goals": ht_home_goals,
                "ht_away_goals": ht_away_goals,
                "ft_home_goals": ft_home_goals,
                "ft_away_goals": ft_away_goals,
                "et_home_goals": et_home_goals,
                "et_away_goals": et_away_goals,
                "pk_home_goals": pk_home_goals,
                "pk_away_goals": pk_away_goals,
                "spf_result": spf_result,
                "rqspf_result": rqspf_result,
                "total_goals_result": total_goals_result,
                "score_result": score_result,
                "half_full_result": half_full_result,
            }
        )

    return {
        "status": "ok",
        "recommendations": recommendations,
        "total": len(recommendations),
        "sales_window": sales_window.as_dict(),
    }


@router.post("/api/models/predict/date/{date}")
def predict_models_for_date(date: str, dry_run: bool = Query(True)):
    """Compatibility endpoint for documented model prediction trigger."""
    if dry_run:
        return {"status": "dry_run", "date": date}
    from scripts.jobs.run_model_prediction import run

    result = run(dry_run=False)
    result["date"] = date
    return result


@router.get("/api/models/predictions")
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
                           COALESCE(mp.raw_model_probability, mp.model_probability),
                           mp.model_probability, mp.market_probability,
                           mp.fair_odds, mp.ev, mp.confidence_score,
                           m.home_team_name, m.away_team_name
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    WHERE mp.match_id = %s
                      AND mp.predict_time < m.kickoff_time
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
                           COALESCE(mp.raw_model_probability, mp.model_probability),
                           mp.model_probability, mp.market_probability,
                           mp.fair_odds, mp.ev, mp.confidence_score,
                           m.home_team_name, m.away_team_name
                    FROM model_predictions mp
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    WHERE mp.predict_time < m.kickoff_time
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
                "raw_model_probability": float(r[6]) if r[6] is not None else None,
                "model_probability": float(r[7]) if r[7] is not None else None,
                "feature_adjusted": (
                    r[6] is not None and r[7] is not None and abs(float(r[7]) - float(r[6])) > 1e-9
                ),
                "market_probability": float(r[8]) if r[8] is not None else None,
                "fair_odds": float(r[9]) if r[9] is not None else None,
                "ev": float(r[10]) if r[10] is not None else None,
                "confidence": float(r[11]) if r[11] is not None else None,
                "home_team": r[12],
                "away_team": r[13],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/models/versions")
def list_model_versions(limit: int = Query(50)):
    """List model versions for API contract compatibility."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, model_name, version, parameters_json, training_window_start,
                       training_window_end, is_active, created_at
                FROM model_versions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return {
        "versions": [
            {
                "id": row[0],
                "model_name": row[1],
                "version": row[2],
                "parameters_json": row[3],
                "training_window_start": str(row[4]) if row[4] else None,
                "training_window_end": str(row[5]) if row[5] else None,
                "is_active": row[6],
                "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/api/recommendations/generate")
def generate_recommendations(date: str | None = Query(None), dry_run: bool = Query(True)):
    """Compatibility endpoint for recommendation generation."""
    if dry_run:
        return {"status": "dry_run", "date": date}
    from scripts.jobs.run_recommendation_candidate import run

    result = run(dry_run=False)
    result["date"] = date
    return result


@router.get("/api/recommendations/daily")
def list_daily_recommendations(date: str | None = Query(None), limit: int = Query(20)):
    """Compatibility endpoint for daily recommendation tickets."""
    result = list_tickets(status=None, limit=limit)
    result["date"] = date
    return result


@router.post("/api/recommendations/{ticket_id}/invalidate")
def invalidate_recommendation(ticket_id: int):
    """Mark a simulation ticket as invalidated."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE simulation_tickets
                SET ticket_status = 'invalidated'
                WHERE id = %s
                """,
                (ticket_id,),
            )
            ok = cur.rowcount > 0
        conn.commit()
    return {"status": "ok" if ok else "not_found", "ticket_id": ticket_id}


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
