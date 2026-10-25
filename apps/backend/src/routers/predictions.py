"""Model predictions and simulation tickets endpoints (Stage 4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from apps.backend.src.model_catalog import CATALOG_VERSION, MODEL_CODES, public_metadata
from scripts.calibration_review import (
    MANUAL_REVIEW_IMPROVEMENT_THRESHOLD,
    MANUAL_REVIEW_SAMPLE_THRESHOLD,
    review_calibration_profile,
    review_calibration_trend,
)
from scripts.prediction_statistics import latest_prediction_ctes
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

# Score-market catch-all outcomes use stable internal codes but must never
# leak those codes into user-facing Agent recommendations.
BF_OTHER_NAMES = {"other_h": "胜其他", "other_d": "平其他", "other_a": "负其他"}


def _option_name(play_type: str, option_code: str, handicap: float | None = None) -> str:
    """Get option display name, respecting play type and handicap."""
    if play_type == "rqspf":
        name = RQSPF_OPTION_NAMES.get(option_code, option_code)
    elif play_type == "bqc" and len(option_code) == 2:
        name = f"{BQC_HT.get(option_code[0], option_code[0])}{BQC_FT.get(option_code[1], option_code[1])}"
    elif play_type == "bf":
        name = BF_OTHER_NAMES.get(option_code, option_code)  # e.g. "1:0", "2:1"
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
    min_ev: float = Query(-1.0, description="最低展示EV，仅用于页面筛选"),
    min_confidence: float = Query(0.0, description="最低展示置信度，仅用于页面筛选"),
):
    """Return today's Agent virtual recommendations at the current official SP.

    Recommendations remain visible during official rest time; the betting
    terminal separately enforces whether the user can currently place a bet.
    """
    sales_window = get_sporttery_sales_window()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH released_items AS (
                    SELECT DISTINCT ON (sti.match_id, sti.play_type, sti.option_code)
                        mp.id AS prediction_id,
                        sti.match_id,
                        sti.play_type,
                        sti.option_code,
                        sti.model_probability,
                        (1.0 / current_odds.sp_value)
                            / current_market.implied_probability_sum
                            AS market_probability,
                        CASE WHEN sti.model_probability > 0
                             THEN 1.0 / sti.model_probability END AS fair_odds,
                        sti.model_probability * current_odds.sp_value - 1 AS current_ev,
                        sti.confidence_score,
                        mp.predict_time,
                        mv.model_name,
                        m.home_team_name,
                        m.away_team_name,
                        m.league_name,
                        m.kickoff_time,
                        m.match_status,
                        COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text)
                            AS official_match_code,
                        current_odds.sp_value,
                        current_odds.handicap,
                        current_odds.snapshot_time,
                        fs.data_completeness_score,
                        st.strategy_pool,
                        st.risk_level
                    FROM simulation_tickets st
                    JOIN simulation_ticket_items sti ON sti.ticket_id = st.id
                    JOIN model_predictions mp ON mp.id = sti.model_prediction_id
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    LEFT JOIN match_feature_snapshots fs
                           ON fs.id = mp.feature_snapshot_id
                    JOIN LATERAL (
                        SELECT os.sp_value, os.handicap, os.snapshot_time
                        FROM official_odds_snapshots os
                        WHERE os.match_id = sti.match_id
                          AND os.play_type = sti.play_type
                          AND os.option_code = CASE
                              WHEN sti.play_type IN ('spf', 'rqspf') THEN CASE sti.option_code
                                  WHEN '3' THEN 'h'
                                  WHEN '1' THEN 'd'
                                  WHEN '0' THEN 'a'
                                  ELSE sti.option_code
                              END
                              ELSE sti.option_code
                          END
                          AND os.is_open = true
                        ORDER BY os.snapshot_time DESC, os.id DESC
                        LIMIT 1
                    ) current_odds ON true
                    JOIN LATERAL (
                        SELECT SUM(1.0 / latest.sp_value)
                                   AS implied_probability_sum
                        FROM (
                            SELECT DISTINCT ON (os.option_code)
                                os.option_code, os.sp_value
                            FROM official_odds_snapshots os
                            WHERE os.match_id = sti.match_id
                              AND os.play_type = sti.play_type
                              AND os.is_open = true
                              AND os.sp_value > 1
                            ORDER BY os.option_code,
                                     os.snapshot_time DESC, os.id DESC
                        ) latest
                    ) current_market ON current_market.implied_probability_sum > 0
                    WHERE (st.created_at AT TIME ZONE 'UTC'
                           AT TIME ZONE 'Asia/Shanghai')::date
                          = timezone('Asia/Shanghai', NOW())::date
                      AND st.ticket_status IN ('generated', 'activated', 'purchased')
                      AND mp.odds_snapshot_id IS NOT NULL
                      AND mp.feature_snapshot_id IS NOT NULL
                      AND mp.validation_status = 'valid'
                      AND COALESCE(
                          (mp.uncertainty_reason->>'model_independent')::boolean,
                          false
                      ) = true
                      AND LOWER(COALESCE(m.match_status, '')) IN ('scheduled', 'selling', 'not_started')
                      AND m.kickoff_time > timezone('Asia/Shanghai', NOW())
                      AND mp.predict_time < m.kickoff_time
                      AND EXISTS (
                          SELECT 1
                          FROM official_markets market
                          WHERE market.match_id = m.id
                            AND market.play_type = mp.play_type
                            AND market.is_open = true
                      )
                      AND sti.model_probability * current_odds.sp_value - 1 > %(min_ev)s
                      AND (%(min_confidence)s <= 0 OR sti.confidence_score >= %(min_confidence)s)
                    ORDER BY sti.match_id, sti.play_type, sti.option_code,
                             st.created_at DESC, sti.id DESC
                )
                SELECT prediction_id, match_id, play_type, option_code,
                       model_probability, market_probability, fair_odds, current_ev,
                       confidence_score, predict_time, model_name,
                       home_team_name, away_team_name, league_name,
                       kickoff_time, match_status, handicap,
                       official_match_code, sp_value,
                       snapshot_time, data_completeness_score,
                       strategy_pool, risk_level
                FROM released_items
                ORDER BY current_ev DESC, confidence_score DESC
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
        confidence = float(r[8]) if r[8] is not None else None
        edge = model_prob - market_prob if market_prob > 0 else 0
        handicap = float(r[16]) if r[16] is not None else None
        official_match_code = r[17]
        sp_value = float(r[18])
        break_even_probability = 1.0 / sp_value
        breakeven_edge = model_prob - break_even_probability
        odds_snapshot_time = r[19]
        data_completeness = float(r[20]) if r[20] is not None else None

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
                "sp_value": round(sp_value, 2),
                "fair_odds": round(fair_odds, 2),
                "ev": round(ev, 4),
                "edge": round(edge, 4),
                "market_edge": round(edge, 4),
                "break_even_probability": round(break_even_probability, 4),
                "breakeven_edge": round(breakeven_edge, 4),
                "confidence": round(confidence, 4) if confidence is not None else None,
                "odds_snapshot_time": odds_snapshot_time.isoformat()
                if hasattr(odds_snapshot_time, "isoformat")
                else str(odds_snapshot_time),
                "data_completeness": round(data_completeness, 1)
                if data_completeness is not None
                else None,
                "validation_status": "valid",
                "model_independent": True,
                "strategy_pool": r[21],
                "risk_level": r[22],
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
                "ht_home_goals": None,
                "ht_away_goals": None,
                "ft_home_goals": None,
                "ft_away_goals": None,
                "et_home_goals": None,
                "et_away_goals": None,
                "pk_home_goals": None,
                "pk_away_goals": None,
                "spf_result": None,
                "rqspf_result": None,
                "total_goals_result": None,
                "score_result": None,
                "half_full_result": None,
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


def _read_prediction_summary(
    cur: Any, latest_ctes: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    cur.execute(
        f"""
        WITH RECURSIVE {latest_ctes}, latest_ids AS (
            SELECT mapped.prediction_id AS id FROM latest_groups g
            JOIN model_prediction_group_options mapped ON mapped.group_id = g.group_id
            UNION ALL
            SELECT id FROM legacy_latest
        )
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE mp.ev > 0) AS positive_ev_count,
            AVG(mp.confidence_score) AS avg_confidence,
            COUNT(DISTINCT mv.model_name) AS model_count,
            MAX(mp.predict_time) AS latest_predict_time
        FROM latest_ids latest
        JOIN LATERAL (
            SELECT p.* FROM model_predictions p WHERE p.id = latest.id OFFSET 0
        ) mp ON true
        JOIN model_versions mv ON mv.id = mp.model_version_id
        JOIN official_matches m ON m.id = mp.match_id
        WHERE mp.validation_status = 'valid'
          AND mp.predict_time < m.kickoff_time
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "total": int(row[0] or 0),
        "positive_ev_count": int(row[1] or 0),
        "avg_confidence": float(row[2]) if row[2] is not None else None,
        "model_count": int(row[3] or 0),
        "latest_predict_time": (
            row[4].isoformat()
            if row[4] is not None and hasattr(row[4], "isoformat")
            else str(row[4])
            if row[4] is not None
            else None
        ),
    }


@router.get("/api/models/predictions")
@router.get("/api/predictions")
def list_predictions(
    match_id: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=500),
    include_summary: bool = True,
    summary_only: bool = False,
):
    """List recent predictions or return only the full-scope summary."""
    summary = None
    with get_db() as conn:
        with conn.cursor() as cur:
            # JIT compilation dominates these index-seek plans at real catalog
            # sizes. Limit the setting to this read transaction; pooled sessions
            # return to their normal settings on commit/rollback.
            cur.execute("SET LOCAL jit = off")
            latest_ctes = latest_prediction_ctes(filter_match=match_id is not None)
            params = {"match_id": match_id, "limit": limit}
            if summary_only:
                summary = _read_prediction_summary(cur, latest_ctes, params)
                return {
                    "predictions": [],
                    "total": summary["total"] if summary is not None else None,
                    "summary": summary,
                }
            cur.execute(
                f"""
                WITH RECURSIVE {latest_ctes}, latest_ids AS (
                    SELECT mapped.prediction_id AS id FROM latest_groups g
                    JOIN model_prediction_group_options mapped ON mapped.group_id = g.group_id
                    UNION ALL
                    SELECT id FROM legacy_latest
                ), recent AS MATERIALIZED (
                    SELECT mp.* FROM latest_ids latest
                    JOIN LATERAL (
                        SELECT p.* FROM model_predictions p WHERE p.id = latest.id OFFSET 0
                    ) mp ON true
                    JOIN model_versions mv ON mv.id = mp.model_version_id
                    JOIN official_matches m ON m.id = mp.match_id
                    WHERE mp.validation_status = 'valid'
                      AND mp.predict_time < m.kickoff_time
                    ORDER BY mp.predict_time DESC, mp.ev DESC, mp.id DESC
                    LIMIT %(limit)s
                )
                SELECT mp.id, mp.match_id, mp.predict_time,
                   mv.model_name, mp.play_type, mp.option_code,
                   COALESCE(mp.raw_model_probability, mp.model_probability),
                   mp.model_probability, mp.market_probability,
                   mp.fair_odds, mp.ev, mp.confidence_score,
                   m.home_team_name, m.away_team_name,
                   mv.id, mv.version, mv.model_type, mv.feature_set_version,
                   fs.id, fs.snapshot_time, fs.feature_version,
                   jsonb_build_object(
                       'strength', (fs.home_team_market_value IS NOT NULL
                               OR fs.away_team_market_value IS NOT NULL
                               OR fs.team_market_value_diff IS NOT NULL
                               OR fs.team_market_value_ratio IS NOT NULL
                               OR fs.home_attack_strength_score IS NOT NULL
                               OR fs.away_attack_strength_score IS NOT NULL
                               OR fs.home_defense_strength_score IS NOT NULL
                               OR fs.away_defense_strength_score IS NOT NULL),
                       'lineup', (fs.home_lineup_confirmed IS NOT NULL
                               OR fs.away_lineup_confirmed IS NOT NULL
                               OR fs.home_starting_11_value IS NOT NULL
                               OR fs.away_starting_11_value IS NOT NULL
                               OR fs.starting_11_value_diff IS NOT NULL
                               OR fs.home_lineup_strength_score IS NOT NULL
                               OR fs.away_lineup_strength_score IS NOT NULL
                               OR fs.lineup_strength_diff IS NOT NULL),
                       'absence', (fs.home_absence_impact_score IS NOT NULL
                               OR fs.away_absence_impact_score IS NOT NULL
                               OR fs.absence_impact_diff IS NOT NULL
                               OR fs.home_key_absence_count IS NOT NULL
                               OR fs.away_key_absence_count IS NOT NULL),
                       'rest', (fs.home_rotation_risk_score IS NOT NULL
                               OR fs.away_rotation_risk_score IS NOT NULL
                               OR fs.rotation_risk_diff IS NOT NULL
                               OR fs.home_rest_days IS NOT NULL
                               OR fs.away_rest_days IS NOT NULL
                               OR fs.rest_days_diff IS NOT NULL),
                       'travel', (fs.stadium_id IS NOT NULL
                               OR fs.away_travel_distance_km IS NOT NULL
                               OR fs.timezone_diff IS NOT NULL
                               OR fs.altitude_m IS NOT NULL
                               OR fs.away_travel_fatigue_score IS NOT NULL),
                       'weather', (fs.temperature_2m IS NOT NULL
                               OR fs.precipitation IS NOT NULL
                               OR fs.wind_speed_10m IS NOT NULL
                               OR fs.weather_impact_score IS NOT NULL
                               OR fs.goal_expectation_weather_adjustment IS NOT NULL),
                       'motivation', (fs.home_motivation_score IS NOT NULL
                               OR fs.away_motivation_score IS NOT NULL
                               OR fs.motivation_diff IS NOT NULL
                               OR fs.home_must_win IS NOT NULL
                               OR fs.away_must_win IS NOT NULL
                               OR fs.home_draw_enough IS NOT NULL
                               OR fs.away_draw_enough IS NOT NULL),
                       'tournament', (fs.home_avoid_strong_opponent_score IS NOT NULL
                               OR fs.away_avoid_strong_opponent_score IS NOT NULL
                               OR fs.home_tanking_risk_score IS NOT NULL
                               OR fs.away_tanking_risk_score IS NOT NULL
                               OR fs.tournament_incentive_risk_score IS NOT NULL)
                   ), od.id, od.snapshot_time
                FROM recent mp
                JOIN model_versions mv ON mv.id = mp.model_version_id
                JOIN official_matches m ON m.id = mp.match_id
                LEFT JOIN match_feature_snapshots fs
                  ON fs.id = mp.feature_snapshot_id AND fs.match_id = mp.match_id
                 AND fs.snapshot_time <= mp.predict_time
                LEFT JOIN official_odds_snapshots od
                  ON od.id = mp.odds_snapshot_id AND od.match_id = mp.match_id
                 AND od.play_type = mp.play_type
                 AND od.option_code = CASE WHEN mp.play_type IN ('spf', 'rqspf') THEN CASE mp.option_code
                     WHEN '3' THEN 'h' WHEN '1' THEN 'd' WHEN '0' THEN 'a'
                     ELSE mp.option_code END ELSE mp.option_code END
                 AND od.snapshot_time <= mp.predict_time
                ORDER BY mp.predict_time DESC, mp.ev DESC, mp.id DESC
                """,
                params,
            )
            rows = cur.fetchall()
            if include_summary:
                summary = _read_prediction_summary(cur, latest_ctes, params)
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
                "research_evidence": {
                    "model_version_id": r[14],
                    "model_version": r[15],
                    "model_type": r[16],
                    "feature_set_version": r[17],
                    "feature_snapshot_id": r[18],
                    "feature_snapshot_time": r[19].isoformat() if r[19] else None,
                    "feature_version": r[20],
                    "feature_categories": [
                        key for key, present in (r[21] or {}).items() if present is True
                    ],
                    "odds_snapshot_id": r[22],
                    "odds_snapshot_time": r[23].isoformat() if r[23] else None,
                },
            }
            for r in rows
        ],
        "total": summary["total"] if summary is not None else None,
        "summary": summary,
    }


@router.get("/api/models/versions")
def list_model_versions(limit: int = Query(50)):
    """List model versions for API contract compatibility."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, model_name, version, parameters_json, training_start_date,
                       training_end_date, is_active, created_at
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
                "training_start_date": str(row[4]) if row[4] else None,
                "training_end_date": str(row[5]) if row[5] else None,
                # Compatibility aliases retained for existing API consumers.
                "training_window_start": str(row[4]) if row[4] else None,
                "training_window_end": str(row[5]) if row[5] else None,
                "is_active": row[6],
                "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/api/models/overview")
def get_prediction_model_overview():
    """Return read-only runtime state for the supported prediction models."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH current_versions AS (
                    SELECT DISTINCT ON (model_name)
                           id, model_name, version, is_active,
                           training_start_date, training_end_date, created_at
                    FROM model_versions
                    WHERE model_name = ANY(%s)
                    ORDER BY model_name, is_active DESC, created_at DESC, id DESC
                ), current_calibrations AS (
                    SELECT DISTINCT ON (model_name, play_type)
                           model_name, play_type, method_name, sample_count,
                           log_loss_before, log_loss_after,
                           (parameters_json ->> 'temperature')::numeric AS temperature,
                           training_end_date
                    FROM probability_calibration_profiles
                    WHERE is_active = true
                    ORDER BY model_name, play_type, created_at DESC, id DESC
                ), prediction_stats AS MATERIALIZED (
                    SELECT mp.model_version_id,
                           COUNT(DISTINCT mp.match_id) AS valid_prediction_match_count,
                           MAX(mp.predict_time) AS latest_prediction_at
                    FROM model_prediction_latest_rows mp
                    JOIN current_versions cv ON cv.id = mp.model_version_id
                    WHERE mp.validation_status = 'valid'
                    GROUP BY mp.model_version_id
                )
                SELECT cv.model_name, cv.id, cv.version, cv.is_active,
                       cv.training_start_date, cv.training_end_date, cv.created_at,
                       COALESCE(prediction_stats.valid_prediction_match_count, 0),
                       prediction_stats.latest_prediction_at,
                       cp.method_name, cp.sample_count, cp.log_loss_before,
                       cp.log_loss_after, cp.temperature, cp.training_end_date
                FROM current_versions cv
                LEFT JOIN prediction_stats ON prediction_stats.model_version_id = cv.id
                LEFT JOIN current_calibrations cp
                  ON cp.model_name = cv.model_name AND cp.play_type = 'spf'
                """,
                (list(MODEL_CODES),),
            )
            rows = cur.fetchall()

    states = {
        row[0]: {
            "code": row[0],
            "isActive": bool(row[3]),
            "version": row[2],
            "versionCreatedAt": row[6].isoformat() if row[6] else None,
            "trainingStartDate": str(row[4]) if row[4] else None,
            "trainingEndDate": str(row[5]) if row[5] else None,
            "validPredictionMatchCount": int(row[7] or 0),
            "latestPredictionAt": row[8].isoformat() if row[8] else None,
            "calibration": (
                {
                    "methodName": row[9],
                    "sampleCount": int(row[10]),
                    "logLossBefore": float(row[11]),
                    "logLossAfter": float(row[12]),
                    "temperature": float(row[13]),
                    "trainingEndDate": str(row[14]) if row[14] else None,
                    "rolloutMode": "shadow",
                }
                if len(row) > 14 and row[9] is not None
                else None
            ),
        }
        for row in rows
    }
    models = [
        states.get(
            code,
            {
                "code": code,
                "isActive": False,
                "version": None,
                "versionCreatedAt": None,
                "trainingStartDate": None,
                "trainingEndDate": None,
                "validPredictionMatchCount": 0,
                "latestPredictionAt": None,
                "calibration": None,
            },
        )
        for code in MODEL_CODES
    ]
    for model in models:
        model["metadata"] = public_metadata(model["code"])
    return {"models": models, "total": len(models), "catalogVersion": CATALOG_VERSION}


@router.get("/api/models/calibration-profiles")
def get_calibration_profiles(limit: int = Query(12, ge=1, le=60)):
    """Return calibration history and advisory review status without promotion."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model_name, play_type, method_name, calibration_version,
                       parameters_json, sample_count, log_loss_before, log_loss_after,
                       training_end_date, is_active, created_at
                FROM probability_calibration_profiles
                WHERE play_type = 'spf'
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    profiles = []
    profiles_by_model: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        raw = {
            "sample_count": int(row[5]),
            "log_loss_before": float(row[6]),
            "log_loss_after": float(row[7]),
        }
        parameters = row[4] or {}
        profile = {
            "modelCode": row[0],
            "playType": row[1],
            "methodName": row[2],
            "version": row[3],
            "temperature": float(parameters["temperature"]),
            "sampleCount": raw["sample_count"],
            "logLossBefore": raw["log_loss_before"],
            "logLossAfter": raw["log_loss_after"],
            "trainingEndDate": str(row[8]) if row[8] else None,
            "isActive": bool(row[9]),
            "createdAt": row[10].isoformat() if row[10] else None,
            "review": review_calibration_profile(raw),
        }
        profiles.append(profile)
        profiles_by_model.setdefault(row[0], []).append(
            {
                "created_at": profile["createdAt"],
                "log_loss_after": raw["log_loss_after"],
                "sample_count": raw["sample_count"],
            }
        )
    trends = [
        {"modelCode": model_code, **review_calibration_trend(model_profiles)}
        for model_code, model_profiles in profiles_by_model.items()
    ]
    return {
        "profiles": profiles,
        "trends": trends,
        "policy": {
            "sampleThreshold": MANUAL_REVIEW_SAMPLE_THRESHOLD,
            "improvementThreshold": MANUAL_REVIEW_IMPROVEMENT_THRESHOLD,
            "affectsDecisionPath": False,
        },
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
