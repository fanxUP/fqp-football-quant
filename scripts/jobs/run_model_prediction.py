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
from scripts.dixon_coles_model import dixon_coles_matrix
from scripts.elo_model import get_or_create_elo, run_elo_1x2_prediction
from scripts.feature_adjustment import GoalRateAdjustment, adjust_goal_rates
from scripts.model_storage import store_committee_vote, store_model_prediction
from scripts.odds_conversion import (
    expected_value,
    full_debias_pipeline,
    normalize_probabilities,
    overround,
)
from scripts.poisson_model import (
    derive_1x2,
    derive_handicap,
    derive_total_goals,
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
    return business_now().replace(tzinfo=None).isoformat(timespec="seconds")


def _latest_feature_snapshot_id(conn: Any, match_id: int) -> int | None:
    """Return the newest feature snapshot for evidence-chain traceability."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM match_feature_snapshots
            WHERE match_id = %s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (match_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _latest_feature_snapshot(conn: Any, match_id: int) -> dict[str, Any] | None:
    """Load the latest pre-match fields used by the explainable adjustment layer."""
    columns = [
        "id",
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
    latest_snapshot_id: int | None = None
    for row in odds_rows:
        snap_id, opt, sp = row
        code = OPTION_MAP.get(opt, opt)
        if code not in odds_dict:
            odds_dict[code] = float(sp)
        if latest_snapshot_id is None:
            latest_snapshot_id = snap_id

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

    # 5b. Derive BF/ZJQ/BQC from SPF score matrix
    if play_type == "spf" and poisson_matrix:
        _store_derived_play_types(
            conn,
            mid,
            poisson_matrix,
            dc_matrix or poisson_matrix,
            active_models,
            lam_h,
            lam_a,
            predict_time,
        )

    # 5. Elo model
    try:
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
        elo_1x2 = dict(market_probs)

    # 6. Write predictions per model
    model_results = {
        "market_baseline": (market_probs, market_probs),
        "maher_poisson": (raw_poisson_probs, poisson_probs),
        "dixon_coles": (raw_dc_probs, dc_probs),
        "elo_rating": (elo_1x2, elo_1x2),
    }

    total_p = 0
    total_v = 0

    for model_name, (raw_probs, probs) in model_results.items():
        mv_id = active_models.get(model_name)
        if mv_id is None:
            continue

        for opt_code in ("3", "1", "0"):
            model_p = probs.get(opt_code, 0.0)
            raw_model_p = raw_probs.get(opt_code, model_p)
            market_p = market_probs.get(opt_code, 0.0)
            sp_val = odds_dict.get(opt_code, 0.0)

            fair_odds = (1.0 / model_p) if model_p and model_p > 0 else None
            ev = expected_value(model_p, sp_val) if sp_val > 0 else 0.0

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
                "odds_snapshot_id": latest_snapshot_id,
                "feature_snapshot_id": feature_snapshot_id,
                "predict_time": predict_time,
                "play_type": play_type,
                "option_code": opt_code,
                "raw_model_probability": round(raw_model_p, 6),
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


def _store_derived_play_types(
    conn: Any,
    mid: int,
    poisson_matrix: dict[str, float],
    dc_matrix: dict[str, float],
    active_models: dict[str, int],
    lam_h: float,
    lam_a: float,
    predict_time: str,
) -> int:
    """Derive and store predictions for BF, ZJQ, BQC from Poisson/DC matrices.

    Calls the sporttery uniform fixed-bonus API to get market odds for
    these play types (not stored in DB yet). Uses SPF score matrices
    to derive model probabilities without re-running models.

    Returns:
        Number of additional predictions stored.
    """
    from scripts.odds_conversion import expected_value
    from scripts.sporttery_client import SportteryClient

    feature_snapshot_id = _latest_feature_snapshot_id(conn, mid)
    total = 0
    poisson_mv = active_models.get("maher_poisson")
    dc_mv = active_models.get("dixon_coles")
    if not poisson_mv:
        return 0

    # Get sporttery matchId from raw_json
    sporttery_mid = None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_json->>'matchId' FROM official_matches WHERE id = %s",
            (mid,),
        )
        row = cur.fetchone()
        if row and row[0]:
            sporttery_mid = row[0]

    market: dict[str, dict[str, float]] = {}

    if not sporttery_mid:
        # Fallback: derive market odds from Poisson model probabilities
        # Apply 8% margin so market_prob < model_prob, creating positive EV
        MARGIN = 1.08
        zjq_probs = derive_total_goals(poisson_matrix)
        market["zjq"] = {k: round(MARGIN / v, 2) if v > 0 else 100.0 for k, v in zjq_probs.items()}

        # BQC: derive from HT/FT lambdas (same heuristic as main code)
        ht_lambda_h = lam_h * 0.45 if lam_h else 0.4
        ht_lambda_a = lam_a * 0.45 if lam_a else 0.3
        ft_lambda_h = lam_h if lam_h else 1.0
        ft_lambda_a = lam_a if lam_a else 0.8
        ht_matrix = score_matrix(ht_lambda_h, ht_lambda_a, max_goals=4)
        ft_matrix = score_matrix(ft_lambda_h, ft_lambda_a, max_goals=4)
        ht_1x2 = derive_1x2(ht_matrix)
        ft_1x2 = derive_1x2(ft_matrix)
        bqc_market: dict[str, float] = {}
        for hc in ("3", "1", "0"):
            for fc in ("3", "1", "0"):
                opt = f"{hc}{fc}"
                prob = ht_1x2.get(hc, 0) * ft_1x2.get(fc, 0)
                if prob > 0.01:
                    bqc_market[opt] = round(MARGIN / prob, 2)
        if bqc_market:
            market["bqc"] = bqc_market

        market["bf"] = {
            score: round(MARGIN / prob, 2) if prob > 0 else 100.0
            for score, prob in poisson_matrix.items()
            if prob >= 0.01
        }
    else:
        # Fetch fixed-bonus odds from uniform API
        try:
            client = SportteryClient()
            bonus = client.get_uniform_fixed_bonus(int(sporttery_mid))
            client.close()
        except Exception:
            bonus = {}

        odds_history = bonus.get("value", {}).get("oddsHistory", {})
        if not odds_history:
            odds_history = {}

        # TTG → zjq (总进球数)
        ttg = odds_history.get("ttgList")
        if ttg:
            market["zjq"] = {}
            for entry in ttg:
                for k, v in entry.items():
                    if k.startswith("s") and k[1:].isdigit() and v:
                        try:
                            market["zjq"][k[1:]] = float(v)
                        except (ValueError, TypeError):
                            pass

        # HAFU → bqc (半全场)
        HAFU_MAP = {
            "hh": "33",
            "hd": "31",
            "ha": "30",
            "dh": "13",
            "dd": "11",
            "da": "10",
            "ah": "03",
            "ad": "01",
            "aa": "00",
        }
        hafu = odds_history.get("hafuList")
        if hafu:
            market["bqc"] = {}
            for entry in hafu:
                for sk, internal_code in HAFU_MAP.items():
                    v = entry.get(sk)
                    if v:
                        try:
                            market["bqc"][internal_code] = float(v)
                        except (ValueError, TypeError):
                            pass

        # CRS → bf (比分)
        crs = odds_history.get("crsList")
        if crs:
            market["bf"] = {}
            for entry in crs:
                for k, v in entry.items():
                    if k.startswith("s") and v:
                        # Convert "s01s00" → "1:0"
                        try:
                            parts = k[1:].split("s")
                            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                score_key = f"{int(parts[0])}:{int(parts[1])}"
                                market["bf"][score_key] = float(v)
                            elif k == "s-1sh":
                                market["bf"]["other_h"] = float(v)
                            elif k == "s-1sd":
                                market["bf"]["other_d"] = float(v)
                            elif k == "s-1sa":
                                market["bf"]["other_a"] = float(v)
                        except (ValueError, TypeError):
                            pass

    # If official odds are unavailable, keep the training pipeline alive with
    # model-derived fair-market odds. These are explicitly synthetic and are
    # never treated as official Sporttery snapshots.
    if not market:
        margin = 1.08
        zjq_probs = derive_total_goals(poisson_matrix)
        market["zjq"] = {k: round(margin / v, 2) for k, v in zjq_probs.items() if v > 0}
        market["bf"] = {
            score: round(margin / prob, 2) for score, prob in poisson_matrix.items() if prob >= 0.01
        }
        ht_matrix = score_matrix(lam_h * 0.45, lam_a * 0.45, max_goals=4)
        ht_1x2 = derive_1x2(ht_matrix)
        ft_1x2 = derive_1x2(poisson_matrix)
        market["bqc"] = {
            f"{hc}{fc}": round(margin / max(ht_1x2.get(hc, 0) * ft_1x2.get(fc, 0), 1e-6), 2)
            for hc in ("3", "1", "0")
            for fc in ("3", "1", "0")
        }

    # ── 1. ZJQ (总进球数) ──
    if "zjq" in market:
        poisson_zjq = derive_total_goals(poisson_matrix)
        dc_zjq = derive_total_goals(dc_matrix) if dc_matrix else poisson_zjq

        for opt_code, market_sp in market["zjq"].items():
            if market_sp <= 0:
                continue
            model_p = poisson_zjq.get(opt_code, 0)
            if model_p <= 0.001:
                continue
            ev = expected_value(model_p, market_sp)
            if ev < 0:
                continue  # skip negative EV

            # Average with DC if available
            if dc_mv and poisson_mv:
                dc_p = dc_zjq.get(opt_code, 0)
                avg_p = (model_p + dc_p) / 2
            else:
                avg_p = model_p

            # Store as Poisson prediction
            for mv_id, _probs, _model_name in [
                (poisson_mv, {opt_code: avg_p}, "maher_poisson"),
            ]:
                if not mv_id:
                    continue
                pred = {
                    "match_id": mid,
                    "model_version_id": mv_id,
                    "odds_snapshot_id": None,
                    "feature_snapshot_id": feature_snapshot_id,
                    "predict_time": predict_time,
                    "play_type": "zjq",
                    "option_code": opt_code,
                    "model_probability": round(avg_p, 6),
                    "market_probability": round(1.0 / market_sp, 6),
                    "fair_odds": round(1.0 / avg_p, 4) if avg_p > 0 else None,
                    "ev": round(ev, 6),
                    "confidence_score": round(min(1.0, avg_p * 3), 4),
                    "risk_score": round(max(0, 1.0 - avg_p * 3), 4),
                }
                store_model_prediction(conn, pred)
                total += 1

    # ── 2. BF (比分 — only top high-probability scores) ──
    if "bf" in market:
        # Sort matrix entries by probability descending, take top 5
        poisson_scores = sorted(poisson_matrix.items(), key=lambda x: -x[1])
        dc_scores = sorted(dc_matrix.items(), key=lambda x: -x[1]) if dc_matrix else poisson_scores

        count = 0
        for poisson_entry, dc_entry in zip(poisson_scores, dc_scores, strict=False):
            score_str = poisson_entry[0]
            p_prob = poisson_entry[1]
            d_prob = dc_entry[1] if dc_matrix else p_prob

            # Only show meaningful scores
            if p_prob < 0.03:
                break

            market_sp = market["bf"].get(score_str, 0)
            if market_sp <= 0:
                continue

            avg_p = (p_prob + d_prob) / 2
            ev = expected_value(avg_p, market_sp)
            if ev < -0.3:
                continue  # skip very negative EV (still show if near break-even)

            for mv_id, _model_name in [
                (poisson_mv, "maher_poisson"),
            ]:
                if not mv_id:
                    continue
                pred = {
                    "match_id": mid,
                    "model_version_id": mv_id,
                    "odds_snapshot_id": None,
                    "feature_snapshot_id": feature_snapshot_id,
                    "predict_time": predict_time,
                    "play_type": "bf",
                    "option_code": score_str,
                    "model_probability": round(avg_p, 6),
                    "market_probability": round(1.0 / market_sp, 6),
                    "fair_odds": round(1.0 / avg_p, 4) if avg_p > 0 else None,
                    "ev": round(ev, 6),
                    "confidence_score": round(min(1.0, avg_p * 3), 4),
                    "risk_score": round(max(0, 1.0 - avg_p * 3), 4),
                }
                store_model_prediction(conn, pred)
                total += 1
                count += 1
                if count >= 5:
                    break

    # ── 3. BQC (半全场 — simplified from score matrix) ──
    if "bqc" in market and len(market["bqc"]) >= 3:
        # Simple heuristic: HT goals ~ 45% of FT, using fraction of total lambda
        ht_lambda_h = lam_h * 0.45 if lam_h else 0.4
        ht_lambda_a = lam_a * 0.45 if lam_a else 0.3
        ft_lambda_h = lam_h if lam_h else 1.0
        ft_lambda_a = lam_a if lam_a else 0.8

        # Compute HT and FT matrices
        ht_matrix = score_matrix(ht_lambda_h, ht_lambda_a, max_goals=4)
        ft_matrix = score_matrix(ft_lambda_h, ft_lambda_a, max_goals=4)

        # Derive HT and FT 1x2
        ht_1x2 = derive_1x2(ht_matrix)
        ft_1x2 = derive_1x2(ft_matrix)

        # BQC = HT result + FT result
        bqc_opts: dict[str, float] = {}
        ht_codes = [("3", "胜"), ("1", "平"), ("0", "负")]
        ft_codes = [("3", "胜"), ("1", "平"), ("0", "负")]
        for hc, _hl in ht_codes:
            for fc, _fl in ft_codes:
                opt = f"{hc}{fc}"  # e.g., "33" for HH, "31" for HD
                prob = ht_1x2.get(hc, 0) * ft_1x2.get(fc, 0)
                if prob > 0.01:
                    bqc_opts[opt] = prob

        for opt_code, model_p in bqc_opts.items():
            market_sp = market["bqc"].get(opt_code, 0)
            if market_sp <= 0:
                continue
            ev = expected_value(model_p, market_sp)
            if ev < -0.5:
                continue

            for mv_id, _model_name in [
                (poisson_mv, "maher_poisson"),
            ]:
                if not mv_id:
                    continue
                pred = {
                    "match_id": mid,
                    "model_version_id": mv_id,
                    "odds_snapshot_id": None,
                    "feature_snapshot_id": feature_snapshot_id,
                    "predict_time": predict_time,
                    "play_type": "bqc",
                    "option_code": opt_code,
                    "model_probability": round(model_p, 6),
                    "market_probability": round(1.0 / market_sp, 6),
                    "fair_odds": round(1.0 / model_p, 4) if model_p > 0 else None,
                    "ev": round(ev, 6),
                    "confidence_score": round(min(1.0, model_p * 3), 4),
                    "risk_score": round(max(0, 1.0 - model_p * 3), 4),
                }
                store_model_prediction(conn, pred)
                total += 1

    return total


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
