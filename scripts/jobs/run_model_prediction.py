"""Model prediction job.

Orchestrates: load odds → run models → write predictions → committee votes.

Stage 4: runs market_baseline + maher_poisson + dixon_coles for SPF play type.

Odds processing chain:
  market_baseline → simple proportional normalization
  maher_poisson   → Shin margin removal (+FLB correction) → lambda estimation → Poisson matrix
  dixon_coles     → Shin margin removal (+FLB correction) → lambda estimation → DC matrix
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.business_time import business_now
from scripts.derived_play_predictions import store_derived_play_predictions
from scripts.dixon_coles_model import dixon_coles_matrix
from scripts.elo_model import run_elo_1x2_prediction
from scripts.feature_adjustment import GoalRateAdjustment, adjust_goal_rates
from scripts.market_metric_validation import MarketMetricValidationError, validate_market
from scripts.model_storage import store_committee_vote, store_model_prediction
from scripts.odds_conversion import (
    full_debias_pipeline,
    normalize_probabilities,
    overround,
)
from scripts.poisson_model import (
    derive_1x2,
    derive_handicap,
    estimate_lambdas_from_odds,
    score_matrix,
)

# Dixon-Coles rho — hardcoded until historical results enable MLE.
# Negative means low scores (0:0, 1:0, 0:1, 1:1) are less common than
# independent Poisson predicts.
DEFAULT_RHO = -0.08
MIN_ELO_MATCHES = 5

# Option code mapping: odds_conversion uses "3"/"1"/"0", snapshots use "h"/"d"/"a"
OPTION_MAP = {"h": "3", "d": "1", "a": "0"}
OPTION_REVERSE = {"3": "h", "1": "d", "0": "a"}


def _now() -> str:
    return business_now().replace(tzinfo=None).isoformat(timespec="seconds")


def _latest_feature_snapshot(conn: Any, match_id: int) -> dict[str, Any] | None:
    """Load the latest pre-match fields used by the explainable adjustment layer."""
    columns = [
        "id",
        "home_team_id",
        "away_team_id",
        "data_completeness_score",
        "lineup_strength_diff",
        "absence_impact_diff",
        "rest_days_diff",
        "motivation_diff",
        "rotation_risk_diff",
        "goal_expectation_weather_adjustment",
    ]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {", ".join(columns)}
            FROM match_feature_snapshots
            WHERE match_id = %s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (match_id,),
        )
        row = cur.fetchone()
    return dict(zip(columns, row, strict=False)) if row else None


def _load_trained_elo_probabilities(
    conn: Any,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Return an Elo signal only when both ordered teams have real history.

    A zero-match initial rating is a placeholder, not model evidence.  Team IDs
    come from the feature snapshot so home/away order cannot be changed by a
    name lookup or database sort order.
    """
    if not feature_snapshot:
        return None
    home_team_id = feature_snapshot.get("home_team_id")
    away_team_id = feature_snapshot.get("away_team_id")
    if not home_team_id or not away_team_id:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT latest.elo_rating, latest.matches_played
            FROM (VALUES (%s, 1), (%s, 2)) AS requested(team_id, team_order)
            LEFT JOIN LATERAL (
                SELECT elo_rating, matches_played
                FROM team_elo_ratings
                WHERE team_id = requested.team_id
                ORDER BY season DESC NULLS LAST, updated_at DESC
                LIMIT 1
            ) latest ON true
            ORDER BY requested.team_order
            """,
            (home_team_id, away_team_id),
        )
        rows = cur.fetchall()

    if len(rows) != 2 or any(
        row[0] is None or int(row[1] or 0) < MIN_ELO_MATCHES for row in rows
    ):
        return None
    return run_elo_1x2_prediction(float(rows[0][0]), float(rows[1][0]))


def _run_impl(match_id: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Run model predictions for active matches."""
    if dry_run:
        return {"status": "dry_run", "message": "model prediction run (dry run)"}

    predict_time = _now()

    with get_db() as conn:
        # 1. Get active model version IDs
        with conn.cursor() as cur:
            cur.execute("SELECT id, model_name FROM model_versions WHERE is_active = true")
            active_models = {row[1]: row[0] for row in cur.fetchall()}

        if not active_models:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE model_versions SET is_active = true "
                    "WHERE model_name = 'market_baseline' AND is_active = false "
                    "RETURNING id"
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                active_models["market_baseline"] = row[0]
        if not active_models:
            return {"status": "error", "error": "no active model versions"}

        # 1b. Load MLE-fitted parameters (if available)
        mle_rho: float | None = None
        with conn.cursor() as cur:
            cur.execute(
                "SELECT parameters_json FROM model_versions "
                "WHERE model_name = 'dixon_coles' AND parameters_json IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row[0]:
                dc_params = row[0]
                if isinstance(dc_params, dict) and "rho" in dc_params:
                    mle_rho = float(dc_params["rho"])

        rho = mle_rho if mle_rho is not None else DEFAULT_RHO

        # 2. Get matches to predict (team names → look up IDs for Elo)
        if match_id:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, home_team_name, away_team_name
                       FROM official_matches WHERE id = %s
                         AND sale_status = 'selling'
                         AND LOWER(COALESCE(match_status, ''))
                             IN ('scheduled', 'selling', 'not_started')
                         AND kickoff_time > timezone('Asia/Shanghai', NOW())
                         AND (sale_stop_time IS NULL
                              OR sale_stop_time > timezone('Asia/Shanghai', NOW()))""",
                    (match_id,),
                )
                match_rows = cur.fetchall()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, home_team_name, away_team_name
                       FROM official_matches
                       WHERE sale_status = 'selling'
                         AND LOWER(COALESCE(match_status, '')) IN ('scheduled', 'selling', 'not_started')
                         AND kickoff_time > timezone('Asia/Shanghai', NOW())
                         AND (sale_stop_time IS NULL OR sale_stop_time > timezone('Asia/Shanghai', NOW()))"""
                )
                match_rows = cur.fetchall()

        if not match_rows:
            return {"status": "ok", "predictions": 0, "note": "no matches to predict"}

        total_predictions = 0
        total_votes = 0

        # 3. Load available markets: only predict for play types that are open
        match_ids = [r[0] for r in match_rows]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT match_id, play_type FROM official_markets
                WHERE match_id = ANY(%s) AND is_open = true
                  AND play_type IN ('spf', 'rqspf')
                """,
                (match_ids,),
            )
            market_rows = cur.fetchall()

        # Build {match_id: [play_types]} map
        available_markets: dict[int, list[str]] = {}
        for mr in market_rows:
            mid = mr[0]
            pt = mr[1]
            if mid not in available_markets:
                available_markets[mid] = []
            available_markets[mid].append(pt)

        if not available_markets:
            return {
                "status": "ok",
                "predictions": 0,
                "votes": 0,
                "matches_processed": 0,
                "note": "no matches with open official markets",
            }

        for match_row in match_rows:
            mid, home_team_name, away_team_name = (
                match_row[0],
                match_row[1],
                match_row[2],
            )
            play_types = available_markets.get(mid, [])
            for play_type in play_types:
                p, v = _predict_match_play_type(
                    conn,
                    mid,
                    home_team_name,
                    away_team_name,
                    play_type,
                    active_models,
                    rho,
                    mle_rho,
                    predict_time,
                )
                total_predictions += p
                total_votes += v

    return {
        "status": "ok",
        "predictions": total_predictions,
        "votes": total_votes,
        "matches_processed": len(match_rows),
    }


def run(match_id: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Run predictions and persist its multi-agent execution record."""
    run_id = start_tracked_job(
        "model_prediction",
        "model_agent",
        {"dry_run": dry_run, "match_id": match_id},
        dependencies=[] if dry_run else ["official_odds_snapshot", "feature_snapshot_build"],
    )
    try:
        result = _run_impl(match_id=match_id, dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


def _predict_match_play_type(
    conn: Any,
    mid: int,
    home_team_name: str,
    away_team_name: str,
    play_type: str,
    active_models: dict[str, int],
    rho: float,
    mle_rho: float | None,
    predict_time: str,
) -> tuple[int, int]:
    """Run prediction pipeline for a single match + play type.

    Loads odds, runs market_baseline / Poisson / Dixon-Coles / Elo,
    stores predictions and committee votes.

    Returns:
        (predictions_count, votes_count)
    """
    feature_snapshot = _latest_feature_snapshot(conn, mid)
    feature_snapshot_id = feature_snapshot.get("id") if feature_snapshot else None

    # 1. Load latest odds for this play type
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, option_code, sp_value
            FROM official_odds_snapshots
            WHERE match_id = %s AND play_type = %s
              AND is_open = true
            ORDER BY snapshot_time DESC
            """,
            (mid, play_type),
        )
        odds_rows = cur.fetchall()

    if not odds_rows:
        return 0, 0

    odds_dict: dict[str, float] = {}
    snapshot_ids: dict[str, int] = {}
    for row in odds_rows:
        snap_id, opt, sp = row
        code = OPTION_MAP.get(opt, opt)
        if code not in odds_dict:
            odds_dict[code] = float(sp)
            snapshot_ids[code] = int(snap_id)

    if not {"3", "1", "0"}.issubset(odds_dict):
        return 0, 0

    # 2. Odds processing
    market_probs = normalize_probabilities(odds_dict)
    shin_flb_result = full_debias_pipeline(odds_dict)
    shin_flb_probs = shin_flb_result["flb_corrected"]
    overround(odds_dict)

    # 3. Get handicap for RQSPF
    handicap: float | None = None
    if play_type == "rqspf":
        with conn.cursor() as cur:
            cur.execute(
                "SELECT handicap FROM official_odds_snapshots "
                "WHERE match_id = %s AND play_type = 'rqspf' AND handicap IS NOT NULL "
                "ORDER BY snapshot_time DESC LIMIT 1",
                (mid,),
            )
            row = cur.fetchone()
            if row and row[0]:
                handicap = float(row[0])

    # 4. Poisson model
    poisson_matrix = None
    raw_poisson_matrix = None
    dc_matrix = None
    raw_dc_matrix = None
    feature_adjustment = GoalRateAdjustment(1.3, 1.1, False, 0.0, 1.0, [])
    try:
        raw_lam_h, raw_lam_a = estimate_lambdas_from_odds(
            shin_flb_probs["3"], shin_flb_probs["1"], shin_flb_probs["0"]
        )
        raw_poisson_matrix = score_matrix(raw_lam_h, raw_lam_a)
        raw_poisson_probs = (
            derive_handicap(raw_poisson_matrix, handicap)
            if play_type == "rqspf" and handicap is not None
            else derive_1x2(raw_poisson_matrix)
        )
        feature_adjustment = adjust_goal_rates(raw_lam_h, raw_lam_a, feature_snapshot)
        lam_h = feature_adjustment.home_lambda
        lam_a = feature_adjustment.away_lambda
        poisson_matrix = score_matrix(lam_h, lam_a)
        if play_type == "rqspf" and handicap is not None:
            poisson_probs = derive_handicap(poisson_matrix, handicap)
        else:
            poisson_probs = derive_1x2(poisson_matrix)
    except Exception:
        lam_h, lam_a = 1.3, 1.1
        raw_lam_h, raw_lam_a = lam_h, lam_a
        raw_poisson_probs = dict(market_probs)
        poisson_probs = dict(market_probs)
        try:
            poisson_matrix = score_matrix(lam_h, lam_a)
            raw_poisson_matrix = poisson_matrix
        except Exception:
            pass

    # 5. Dixon-Coles model
    try:
        raw_dc_matrix = dixon_coles_matrix(raw_lam_h, raw_lam_a, rho)
        raw_dc_probs = (
            derive_handicap(raw_dc_matrix, handicap)
            if play_type == "rqspf" and handicap is not None
            else derive_1x2(raw_dc_matrix)
        )
        dc_matrix = dixon_coles_matrix(lam_h, lam_a, rho)
        if play_type == "rqspf" and handicap is not None:
            dc_probs = derive_handicap(dc_matrix, handicap)
        else:
            dc_probs = derive_1x2(dc_matrix)
    except Exception:
        raw_dc_probs = dict(raw_poisson_probs)
        dc_probs = dict(poisson_probs)
        raw_dc_matrix = raw_poisson_matrix
        dc_matrix = poisson_matrix

    # 5b. Derive BF/ZJQ/BQC from SPF score matrix
    derived_predictions = 0
    if play_type == "spf" and poisson_matrix and raw_poisson_matrix:
        derived_predictions = store_derived_play_predictions(
            conn=conn,
            match_id=mid,
            active_models=active_models,
            raw_poisson_matrix=raw_poisson_matrix,
            poisson_matrix=poisson_matrix,
            raw_dc_matrix=raw_dc_matrix or raw_poisson_matrix,
            dc_matrix=dc_matrix or poisson_matrix,
            raw_lambdas=(raw_lam_h, raw_lam_a),
            adjusted_lambdas=(lam_h, lam_a),
            feature_snapshot_id=feature_snapshot_id,
            predict_time=predict_time,
        )

    # 5. Elo model. Cold-start ratings are placeholders and must not become
    # independent positive-EV signals.
    try:
        trained_elo = _load_trained_elo_probabilities(conn, feature_snapshot)
        elo_is_independent = trained_elo is not None
        elo_1x2 = trained_elo or dict(market_probs)
    except Exception:
        elo_is_independent = False
        elo_1x2 = dict(market_probs)

    # 6. Write predictions per model
    model_results = {
        "market_baseline": (market_probs, market_probs),
        "maher_poisson": (raw_poisson_probs, poisson_probs),
        "dixon_coles": (raw_dc_probs, dc_probs),
        "elo_rating": (elo_1x2, elo_1x2),
    }
    model_independence = {
        "market_baseline": False,
        "maher_poisson": False,
        "dixon_coles": False,
        "elo_rating": elo_is_independent,
    }

    total_p = derived_predictions
    total_v = 0

    for model_name, (raw_probs, probs) in model_results.items():
        mv_id = active_models.get(model_name)
        if mv_id is None:
            continue

        try:
            option_metrics = validate_market(
                model_probabilities=probs,
                market_probabilities=market_probs,
                odds_by_option=odds_dict,
                snapshot_ids=snapshot_ids,
            )
        except MarketMetricValidationError:
            continue

        for opt_code in ("3", "1", "0"):
            model_p = probs.get(opt_code, 0.0)
            raw_model_p = raw_probs.get(opt_code, model_p)
            market_p = market_probs.get(opt_code, 0.0)

            fair_odds = (1.0 / model_p) if model_p and model_p > 0 else None
            metric = option_metrics[opt_code]
            stored_model_p = round(model_p, 6)
            stored_market_p = round(market_p, 6)
            stored_break_even = round(metric.break_even_probability, 6)

            uncertainty = _model_std(
                [
                    market_probs.get(opt_code, 0),
                    poisson_probs.get(opt_code, 0),
                    dc_probs.get(opt_code, 0),
                    elo_1x2.get(opt_code, 0),
                ]
            )

            pred = {
                "match_id": mid,
                "model_version_id": mv_id,
                "odds_snapshot_id": snapshot_ids[opt_code],
                "feature_snapshot_id": feature_snapshot_id,
                "predict_time": predict_time,
                "play_type": play_type,
                "option_code": opt_code,
                "raw_model_probability": round(raw_model_p, 6),
                "model_probability": stored_model_p,
                "market_probability": stored_market_p,
                "probability_lower_bound": round(max(0, model_p - uncertainty * 2), 6),
                "probability_upper_bound": round(min(1, model_p + uncertainty * 2), 6),
                "uncertainty_score": round(uncertainty, 6),
                "adjusted_probability": round(model_p, 6),
                "fair_odds": round(fair_odds, 4) if fair_odds else None,
                "ev": round(stored_model_p * odds_dict[opt_code] - 1.0, 6),
                "break_even_probability": stored_break_even,
                "market_edge": round(stored_model_p - stored_market_p, 6),
                "breakeven_edge": round(stored_model_p - stored_break_even, 6),
                "validation_status": "valid",
                "validation_errors": [],
                "calculation_version": "market_metrics_v2",
                "confidence_score": round(max(0, 1.0 - uncertainty * 3), 4),
                "risk_score": round(uncertainty * 3, 4),
                "uncertainty_reason": {
                    "model_std": round(uncertainty, 6),
                    "rho": rho if model_name == "dixon_coles" else None,
                    "rho_source": "mle"
                    if (model_name == "dixon_coles" and mle_rho is not None)
                    else "default",
                    "margin_removal": "shin_flb"
                    if model_name in ("maher_poisson", "dixon_coles")
                    else "proportional",
                    "elo_based": model_name == "elo_rating",
                    "model_independent": model_independence[model_name],
                    "feature_adjustment": {
                        "version": feature_adjustment.version,
                        "applied": feature_adjustment.applied
                        and model_name in ("maher_poisson", "dixon_coles"),
                        "snapshot_id": feature_snapshot_id,
                        "home_log_shift": feature_adjustment.home_log_shift,
                        "total_goal_multiplier": feature_adjustment.total_goal_multiplier,
                        "reasons": feature_adjustment.reasons,
                    },
                },
            }
            store_model_prediction(conn, pred)
            total_p += 1

        # Committee votes
        for opt_code in ("3", "1", "0"):
            p = probs.get(opt_code, 0)
            direction = "strong" if p > 0.40 else ("weak" if p > 0.30 else "against")
            direction_full = f"{direction}_{OPTION_REVERSE.get(opt_code, opt_code)}"
            vote = {
                "match_id": mid,
                "play_type": play_type,
                "option_code": opt_code,
                "prediction_time": predict_time,
                "model_version_id": mv_id,
                "model_name": model_name,
                "model_probability": round(p, 6),
                "vote_direction": direction_full,
                "vote_weight": 1.0,
            }
            store_committee_vote(conn, vote)
            total_v += 1

    return total_p, total_v


def _model_std(values: list[float]) -> float:
    """Standard deviation among model predictions for the same option."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance**0.5


if __name__ == "__main__":
    import sys

    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dry = "--dry-run" in sys.argv
    result = run(match_id=mid, dry_run=dry)
    print(result)
