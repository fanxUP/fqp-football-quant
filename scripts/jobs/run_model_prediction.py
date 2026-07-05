"""Model prediction job.

Orchestrates: load odds → run models → write predictions → committee votes.

Stage 4: runs market_baseline + maher_poisson + dixon_coles for SPF play type.

Odds processing chain:
  market_baseline → simple proportional normalization
  maher_poisson   → Shin margin removal (+FLB correction) → lambda estimation → Poisson matrix
  dixon_coles     → Shin margin removal (+FLB correction) → lambda estimation → DC matrix
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.dixon_coles_model import dixon_coles_matrix
from scripts.elo_model import get_or_create_elo, run_elo_1x2_prediction
from scripts.model_storage import store_committee_vote, store_model_prediction
from scripts.odds_conversion import (
    expected_value,
    full_debias_pipeline,
    normalize_probabilities,
    overround,
)
from scripts.poisson_model import (
    derive_1x2,
    estimate_lambdas_from_odds,
    score_matrix,
)

# Dixon-Coles rho — hardcoded until historical results enable MLE.
# Negative means low scores (0:0, 1:0, 0:1, 1:1) are less common than
# independent Poisson predicts.
DEFAULT_RHO = -0.08

# Option code mapping: odds_conversion uses "3"/"1"/"0", snapshots use "h"/"d"/"a"
OPTION_MAP = {"h": "3", "d": "1", "a": "0"}
OPTION_REVERSE = {"3": "h", "1": "d", "0": "a"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run(match_id: int | None = None, dry_run: bool = False) -> dict[str, Any]:
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
                       FROM official_matches WHERE id = %s""",
                    (match_id,),
                )
                match_rows = cur.fetchall()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, home_team_name, away_team_name
                       FROM official_matches WHERE match_status = 'Selling'"""
                )
                match_rows = cur.fetchall()

        if not match_rows:
            return {"status": "ok", "predictions": 0, "note": "no matches to predict"}

        total_predictions = 0
        total_votes = 0

        for match_row in match_rows:
            mid, home_team_name, away_team_name = (
                match_row[0],
                match_row[1],
                match_row[2],
            )
            # 3. Load latest SPF odds for this match
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, option_code, sp_value
                    FROM official_odds_snapshots
                    WHERE match_id = %s AND play_type = 'spf'
                    ORDER BY snapshot_time DESC
                    """,
                    (mid,),
                )
                odds_rows = cur.fetchall()

            if not odds_rows:
                continue

            odds_dict: dict[str, float] = {}
            latest_snapshot_id: int | None = None
            for row in odds_rows:
                snap_id, opt, sp = row
                code = OPTION_MAP.get(opt, opt)
                if code not in odds_dict:
                    odds_dict[code] = float(sp)
                if latest_snapshot_id is None:
                    latest_snapshot_id = snap_id

            if len(odds_dict) < 3:
                continue

            # 4. Odds processing: two pipelines
            #    a) Market baseline — simple proportional normalization
            #    b) Shin+FLB — sophisticated margin removal + bias correction
            market_probs = normalize_probabilities(odds_dict)

            # Shin + FLB debias pipeline for Poisson/DC model inputs
            shin_flb_result = full_debias_pipeline(odds_dict)
            shin_flb_probs = shin_flb_result["flb_corrected"]
            overround(odds_dict)  # rough proxy; actual z solved inside shin_method

            # 5. Poisson: Shin/FLB probs → lambdas → score matrix → 1x2
            try:
                lam_h, lam_a = estimate_lambdas_from_odds(
                    shin_flb_probs["3"], shin_flb_probs["1"], shin_flb_probs["0"]
                )
                poisson_matrix = score_matrix(lam_h, lam_a)
                poisson_1x2 = derive_1x2(poisson_matrix)
            except Exception:
                lam_h, lam_a = 1.3, 1.1
                poisson_1x2 = dict(market_probs)

            # 6. Dixon-Coles: Shin/FLB probs + Poisson lambdas → DC matrix → 1x2
            try:
                dc_matrix = dixon_coles_matrix(lam_h, lam_a, rho)
                dc_1x2 = derive_1x2(dc_matrix)
            except Exception:
                dc_1x2 = dict(poisson_1x2)

            # 7. Elo rating model: pure historical strength, no odds dependency
            try:
                # Look up team IDs from teams table by name
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM teams WHERE team_name_cn IN (%s, %s) ORDER BY id",
                        (home_team_name, away_team_name),
                    )
                    team_rows = cur.fetchall()
                team_ids = [r[0] for r in team_rows]
                if len(team_ids) >= 2:
                    home_elo, _ = get_or_create_elo(conn, team_ids[0])
                    away_elo, _ = get_or_create_elo(conn, team_ids[1])
                    elo_1x2 = run_elo_1x2_prediction(home_elo, away_elo)
                else:
                    elo_1x2 = dict(market_probs)
            except Exception:
                # Fallback: use market baseline if Elo unavailable
                elo_1x2 = dict(market_probs)

            # 8. Write predictions
            model_results = {
                "market_baseline": market_probs,
                "maher_poisson": poisson_1x2,
                "dixon_coles": dc_1x2,
                "elo_rating": elo_1x2,
            }

            for model_name, probs in model_results.items():
                mv_id = active_models.get(model_name)
                if mv_id is None:
                    continue

                for opt_code in ("3", "1", "0"):
                    model_p = probs.get(opt_code, 0.0)
                    market_p = market_probs.get(opt_code, 0.0)
                    sp_val = odds_dict.get(opt_code, 0.0)

                    fair_odds = (1.0 / model_p) if model_p and model_p > 0 else None
                    ev = expected_value(model_p, sp_val) if sp_val > 0 else 0.0

                    uncertainty = _model_std(
                        [
                            market_probs.get(opt_code, 0),
                            poisson_1x2.get(opt_code, 0),
                            dc_1x2.get(opt_code, 0),
                            elo_1x2.get(opt_code, 0),
                        ]
                    )

                    pred = {
                        "match_id": mid,
                        "model_version_id": mv_id,
                        "odds_snapshot_id": latest_snapshot_id,
                        "predict_time": predict_time,
                        "play_type": "spf",
                        "option_code": opt_code,
                        "model_probability": round(model_p, 6),
                        "market_probability": round(market_p, 6),
                        "probability_lower_bound": round(max(0, model_p - uncertainty * 2), 6),
                        "probability_upper_bound": round(min(1, model_p + uncertainty * 2), 6),
                        "uncertainty_score": round(uncertainty, 6),
                        "adjusted_probability": round(model_p, 6),
                        "fair_odds": round(fair_odds, 4) if fair_odds else None,
                        "ev": round(ev, 6),
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
                        },
                    }
                    store_model_prediction(conn, pred)
                    total_predictions += 1

                # 8. Committee votes
                for opt_code in ("3", "1", "0"):
                    p = probs.get(opt_code, 0)
                    direction = "strong" if p > 0.40 else ("weak" if p > 0.30 else "against")
                    direction_full = f"{direction}_{OPTION_REVERSE.get(opt_code, opt_code)}"
                    vote = {
                        "match_id": mid,
                        "play_type": "spf",
                        "option_code": opt_code,
                        "prediction_time": predict_time,
                        "model_version_id": mv_id,
                        "model_name": model_name,
                        "model_probability": round(p, 6),
                        "vote_direction": direction_full,
                        "vote_weight": 1.0,
                    }
                    store_committee_vote(conn, vote)
                    total_votes += 1

    return {
        "status": "ok",
        "predictions": total_predictions,
        "votes": total_votes,
        "matches_processed": len(match_rows),
    }


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
