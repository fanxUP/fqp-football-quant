"""Model prediction job.

Orchestrates: load odds → run models → write predictions → committee votes.

Stage 4: runs market_baseline + maher_poisson + dixon_coles for SPF play type.

Odds processing chain:
  market_baseline → simple proportional normalization
  maher_poisson   → Shin margin removal (+FLB correction) → lambda estimation → Poisson matrix
  dixon_coles     → Shin margin removal (+FLB correction) → lambda estimation → DC matrix
"""

from __future__ import annotations

import logging
import math
import uuid
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.errors import LockNotAvailable

from apps.backend.src.db import get_db
from apps.backend.src.deployment_version import RELEASE_ID
from scripts.adaboost_shadow_model import load_probabilities as load_adaboost_shadow_probabilities
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.bayesian_form_model import probabilities_from_team_outcomes
from scripts.bivariate_poisson_model import bivariate_score_matrix
from scripts.business_time import business_now
from scripts.derived_play_predictions import store_derived_play_predictions
from scripts.dixon_coles_model import dixon_coles_matrix
from scripts.elo_model import run_elo_1x2_prediction
from scripts.extra_trees_shadow_model import (
    load_probabilities as load_extra_trees_shadow_probabilities,
)
from scripts.feature_adjustment import GoalRateAdjustment, adjust_goal_rates
from scripts.feature_storage import load_latest_match_feature_snapshot
from scripts.glicko2_model import Glicko2Rating
from scripts.glicko2_model import predict_1x2 as glicko2_predict_1x2
from scripts.hist_gradient_boosting_shadow_model import (
    load_probabilities as load_hist_gradient_boosting_shadow_probabilities,
)
from scripts.knn_shadow_model import load_probabilities as load_knn_shadow_probabilities
from scripts.lda_shadow_model import load_probabilities as load_lda_shadow_probabilities
from scripts.logistic_shadow_model import load_probabilities as load_logistic_shadow_probabilities
from scripts.maher_goal_rate_runtime import (
    MIN_MAHER_MATCHES as _MIN_MAHER_MATCHES,
)
from scripts.maher_goal_rate_runtime import (
    TrainedGoalRates,
)
from scripts.maher_goal_rate_runtime import (
    load_trained_goal_rates as _load_trained_goal_rates,
)
from scripts.market_metric_validation import MarketMetricValidationError, validate_market
from scripts.mlp_shadow_model import load_probabilities as load_mlp_shadow_probabilities
from scripts.model_prediction_run_identity import (
    build_model_artifact_identity,
    fingerprint_runtime_sources,
)
from scripts.model_prediction_run_storage import (
    create_prediction_run,
    fail_prediction_run,
    finalize_prediction_run,
    store_prediction_group,
    update_prediction_run_manifest,
)
from scripts.model_signal_policy import (
    MODEL_FAMILIES,
    committee_weights,
    disagreement_diagnostic,
    supports_market,
)
from scripts.model_storage import safe_fair_odds as _safe_fair_odds
from scripts.model_storage import store_committee_vote, store_model_prediction
from scripts.naive_bayes_shadow_model import (
    load_probabilities as load_naive_bayes_shadow_probabilities,
)
from scripts.negative_binomial_model import negative_binomial_score_matrix
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
from scripts.prediction_input_fence import capture_prediction_input_fence
from scripts.prediction_input_updates import InputUpdateSuperseded
from scripts.prediction_job_execution import EXECUTION_PROTOCOL, prediction_execution
from scripts.random_forest_shadow_model import (
    load_probabilities as load_random_forest_shadow_probabilities,
)
from scripts.svm_shadow_model import load_probabilities as load_svm_shadow_probabilities
from scripts.xgboost_shadow_model import load_probabilities as load_xgboost_shadow_probabilities

# Dixon-Coles rho — hardcoded until historical results enable MLE.
# Negative means low scores (0:0, 1:0, 0:1, 1:1) are less common than
# independent Poisson predicts.
DEFAULT_RHO = -0.08
logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PREDICTION_SOURCE_PATHS = (
    "scripts/jobs/run_model_prediction.py",
    "apps/backend/src/db.py",
    "apps/backend/src/deployment_version.py",
    "scripts/agents/task_queue.py",
    "scripts/prediction_job_execution.py",
    "scripts/bayesian_form_model.py",
    "scripts/bivariate_poisson_model.py",
    "scripts/business_time.py",
    "scripts/dixon_coles_model.py",
    "scripts/elo_model.py",
    "scripts/extra_trees_shadow_model.py",
    "scripts/feature_adjustment.py",
    "scripts/feature_storage.py",
    "scripts/glicko2_model.py",
    "scripts/hist_gradient_boosting_shadow_model.py",
    "scripts/knn_shadow_model.py",
    "scripts/lda_shadow_model.py",
    "scripts/logistic_shadow_model.py",
    "scripts/maher_goal_rate_runtime.py",
    "scripts/market_metric_validation.py",
    "scripts/model_signal_policy.py",
    "scripts/mlp_shadow_model.py",
    "scripts/naive_bayes_shadow_model.py",
    "scripts/negative_binomial_model.py",
    "scripts/odds_conversion.py",
    "scripts/poisson_model.py",
    "scripts/random_forest_shadow_model.py",
    "scripts/svm_shadow_model.py",
    "scripts/xgboost_shadow_model.py",
    "scripts/adaboost_shadow_model.py",
    "scripts/model_storage.py",
    "scripts/derived_play_predictions.py",
    "scripts/model_prediction_run_identity.py",
    "scripts/model_prediction_run_storage.py",
    "scripts/model_prediction_run_loader.py",
    "scripts/prediction_input_fence.py",
    "scripts/prediction_input_updates.py",
)
MIN_ELO_MATCHES = 5
MIN_MAHER_MATCHES = _MIN_MAHER_MATCHES
MIN_GLICKO2_MATCHES = 8
MAX_GLICKO2_DEVIATION = 160.0
MIN_BIVARIATE_TRAINING_MATCHES = 100
MIN_NEGATIVE_BINOMIAL_TRAINING_MATCHES = 100
# Option code mapping: odds_conversion uses "3"/"1"/"0", snapshots use "h"/"d"/"a"
OPTION_MAP = {"h": "3", "d": "1", "a": "0"}
OPTION_REVERSE = {"3": "h", "1": "d", "0": "a"}


def _load_trained_bivariate_shared_component(
    model_parameters: dict[str, dict[str, Any]],
    goal_rates: TrainedGoalRates | Any | None,
) -> float | None:
    """Return a fitted shared-goal rate only when it is safe for both teams."""
    parameters = model_parameters.get("bivariate_poisson")
    if not parameters or parameters.get("converged") is not True or goal_rates is None:
        return None
    if int(parameters.get("n_matches") or 0) < MIN_BIVARIATE_TRAINING_MATCHES:
        return None
    try:
        component = float(parameters["shared_goal_component"])
        limiting_rate = min(float(goal_rates.home_lambda), float(goal_rates.away_lambda))
    except KeyError, TypeError, ValueError:
        return None
    if not math.isfinite(component) or component < 0 or component >= limiting_rate:
        return None
    return component


def _load_trained_negative_binomial_dispersion(
    model_parameters: dict[str, dict[str, Any]], goal_rates: TrainedGoalRates | Any | None
) -> float | None:
    """Use fitted over-dispersion only with a converged historical goal-rate model."""
    parameters = model_parameters.get("negative_binomial_shadow")
    if not parameters or parameters.get("converged") is not True or goal_rates is None:
        return None
    if int(parameters.get("n_matches") or 0) < MIN_NEGATIVE_BINOMIAL_TRAINING_MATCHES:
        return None
    try:
        dispersion = float(parameters["dispersion"])
    except KeyError, TypeError, ValueError:
        return None
    if not math.isfinite(dispersion) or not 0.05 <= dispersion <= 100.0:
        return None
    return dispersion


def _load_xgboost_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use XGBoost only after a persisted temporal-validation profile exists."""
    return load_xgboost_shadow_probabilities(
        model_parameters.get("xgboost_shadow"), feature_snapshot
    )


def _load_logistic_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use logistic regression only after persisted temporal validation exists."""
    return load_logistic_shadow_probabilities(
        model_parameters.get("logistic_shadow"), feature_snapshot
    )


def _load_random_forest_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use random forest only after its persisted temporal validation exists."""
    return load_random_forest_shadow_probabilities(
        model_parameters.get("random_forest_shadow"), feature_snapshot
    )


def _load_extra_trees_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use extra trees only after its persisted temporal validation exists."""
    return load_extra_trees_shadow_probabilities(
        model_parameters.get("extra_trees_shadow"), feature_snapshot
    )


def _load_hist_gradient_boosting_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use histogram boosting only after persisted temporal validation exists."""
    return load_hist_gradient_boosting_shadow_probabilities(
        model_parameters.get("hist_gradient_boosting_shadow"), feature_snapshot
    )


def _load_adaboost_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use AdaBoost only after its persisted temporal validation exists."""
    return load_adaboost_shadow_probabilities(
        model_parameters.get("adaboost_shadow"), feature_snapshot
    )


def _load_lda_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use LDA only after its persisted temporal validation exists."""
    return load_lda_shadow_probabilities(model_parameters.get("lda_shadow"), feature_snapshot)


def _load_knn_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use KNN only after its persisted temporal validation exists."""
    return load_knn_shadow_probabilities(model_parameters.get("knn_shadow"), feature_snapshot)


def _load_mlp_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]], feature_snapshot: dict[str, Any] | None
) -> dict[str, float] | None:
    return load_mlp_shadow_probabilities(model_parameters.get("mlp_shadow"), feature_snapshot)


def _load_naive_bayes_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]], feature_snapshot: dict[str, Any] | None
) -> dict[str, float] | None:
    return load_naive_bayes_shadow_probabilities(
        model_parameters.get("naive_bayes_shadow"), feature_snapshot
    )


def _load_svm_shadow_probabilities(
    model_parameters: dict[str, dict[str, Any]], feature_snapshot: dict[str, Any]
) -> dict[str, float] | None:
    return load_svm_shadow_probabilities(model_parameters.get("svm_shadow"), feature_snapshot)


def _load_bayesian_form_probabilities(
    conn: Any,
    match_id: int,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Use official settled results strictly before this match's kickoff time."""
    if not feature_snapshot:
        return None
    home_team_id = feature_snapshot.get("home_team_id")
    away_team_id = feature_snapshot.get("away_team_id")
    if not home_team_id or not away_team_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH current_match AS (
                SELECT kickoff_time FROM official_matches WHERE id = %s
            ), requested(team_id, team_order) AS (
                VALUES (%s, 1), (%s, 2)
            ), historical AS (
                SELECT m.kickoff_time,
                       home_team.id AS home_team_id,
                       away_team.id AS away_team_id,
                       r.full_home_goals,
                       r.full_away_goals
                FROM official_matches m
                JOIN official_results r ON r.match_id = m.id
                JOIN LATERAL (
                    SELECT id FROM teams WHERE team_name_cn = m.home_team_name ORDER BY id LIMIT 1
                ) home_team ON true
                JOIN LATERAL (
                    SELECT id FROM teams WHERE team_name_cn = m.away_team_name ORDER BY id LIMIT 1
                ) away_team ON true
                CROSS JOIN current_match
                WHERE m.kickoff_time < current_match.kickoff_time
                  AND r.result_status IN ('final', 'confirmed')
                  AND r.full_home_goals IS NOT NULL
                  AND r.full_away_goals IS NOT NULL
            ), recent AS (
                SELECT requested.team_order,
                       CASE
                           WHEN historical.home_team_id = requested.team_id
                             THEN CASE WHEN historical.full_home_goals > historical.full_away_goals THEN '3'
                                       WHEN historical.full_home_goals = historical.full_away_goals THEN '1' ELSE '0' END
                           ELSE CASE WHEN historical.full_away_goals > historical.full_home_goals THEN '3'
                                     WHEN historical.full_away_goals = historical.full_home_goals THEN '1' ELSE '0' END
                       END AS outcome_code,
                       ROW_NUMBER() OVER (
                           PARTITION BY requested.team_order ORDER BY historical.kickoff_time DESC
                       ) AS recency
                FROM requested
                JOIN historical ON requested.team_id IN (historical.home_team_id, historical.away_team_id)
            )
            SELECT team_order, outcome_code FROM recent WHERE recency <= 12 ORDER BY team_order, recency
            """,
            (match_id, home_team_id, away_team_id),
        )
        rows = cur.fetchall()
    home_outcomes = [str(row[1]) for row in rows if int(row[0]) == 1]
    away_outcomes = [str(row[1]) for row in rows if int(row[0]) == 2]
    return probabilities_from_team_outcomes(home_outcomes, away_outcomes)


def _now() -> str:
    return business_now().replace(tzinfo=None).isoformat(timespec="seconds")


def _latest_feature_snapshot(
    conn: Any, match_id: int, *, as_of: datetime | str
) -> dict[str, Any] | None:
    """Use the same complete snapshot schema as storage and training."""
    return load_latest_match_feature_snapshot(conn, match_id, as_of=as_of)


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

    if len(rows) != 2 or any(row[0] is None or int(row[1] or 0) < MIN_ELO_MATCHES for row in rows):
        return None
    return run_elo_1x2_prediction(float(rows[0][0]), float(rows[1][0]))


def _load_trained_glicko2_probabilities(
    conn: Any,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Return an uncertainty-aware rating signal only after both teams stabilize."""
    if not feature_snapshot:
        return None
    home_team_id = feature_snapshot.get("home_team_id")
    away_team_id = feature_snapshot.get("away_team_id")
    if not home_team_id or not away_team_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT latest.rating, latest.rating_deviation, latest.volatility, latest.matches_played
            FROM (VALUES (%s, 1), (%s, 2)) AS requested(team_id, team_order)
            LEFT JOIN LATERAL (
                SELECT rating, rating_deviation, volatility, matches_played
                FROM team_glicko2_ratings
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
        row[0] is None
        or int(row[3] or 0) < MIN_GLICKO2_MATCHES
        or float(row[1] or MAX_GLICKO2_DEVIATION + 1) > MAX_GLICKO2_DEVIATION
        for row in rows
    ):
        return None
    states = [
        Glicko2Rating(
            rating=float(row[0]),
            deviation=float(row[1]),
            volatility=float(row[2]),
            matches_played=int(row[3]),
        )
        for row in rows
    ]
    return glicko2_predict_1x2(states[0], states[1])


def _run_impl(
    match_id: int | None = None,
    dry_run: bool = False,
    prediction_run_id: uuid.UUID | str | None = None,
    execution_conn: Any = None,
) -> dict[str, Any]:
    """Run model predictions for active matches."""
    if dry_run:
        return {"status": "dry_run", "message": "model prediction run (dry run)"}

    predict_time = _now()

    with nullcontext(execution_conn) if execution_conn is not None else get_db() as conn:
        # 1. Get active model version IDs
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, model_name, parameters_json FROM model_versions WHERE is_active = true"
            )
            model_rows = cur.fetchall()
            active_models = {row[1]: row[0] for row in model_rows}
            model_parameters = {
                row[1]: row[2] for row in model_rows if len(row) > 2 and isinstance(row[2], dict)
            }

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

        model_artifact_identities = {}
        if prediction_run_id is not None:
            for model_name, model_version_id in active_models.items():
                try:
                    training_manifest = None
                    if model_name == "maher_poisson":
                        from scripts.model_training_manifest_storage import load_training_manifest

                        try:
                            training_manifest = load_training_manifest(conn, model_version_id)
                        except ValueError:
                            # Invalid persisted audit data remains incomplete, but must not
                            # suppress ordinary predictions for this legacy-safe path.
                            training_manifest = {}
                    model_artifact_identities[model_name] = build_model_artifact_identity(
                        model_version_id,
                        model_name,
                        model_parameters.get(model_name, {}),
                        artifact_root=_PROJECT_ROOT,
                        training_manifest=training_manifest,
                    )
                except Exception:
                    model_artifact_identities[model_name] = {
                        "model_version_id": int(model_version_id),
                        "model_name": model_name,
                        "provenance_status": "incomplete",
                        "parameters_sha256": None,
                        "artifact": None,
                        "reason": "artifact_identity_unavailable",
                    }
        model_manifest = [
            model_artifact_identities[name] for name in sorted(model_artifact_identities)
        ]
        run_provenance_status = (
            "complete"
            if model_manifest
            and all(item["provenance_status"] == "complete" for item in model_manifest)
            else "incomplete"
        )
        if prediction_run_id is not None:
            update_prediction_run_manifest(
                conn,
                run_id=prediction_run_id,
                model_manifest=model_manifest,
                input_manifest={"match_id_filter": match_id, "predict_time": predict_time},
                provenance_status=run_provenance_status,
            )
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

        if prediction_run_id is not None:
            update_prediction_run_manifest(
                conn,
                run_id=prediction_run_id,
                model_manifest=model_manifest,
                input_manifest={
                    "match_id_filter": match_id,
                    "match_ids": sorted(int(row[0]) for row in match_rows),
                    "predict_time": predict_time,
                },
                provenance_status=run_provenance_status,
            )

        if not match_rows:
            return {
                "status": "ok",
                "predictions": 0,
                "note": "no matches to predict",
                "completion_reason": "no_matches",
                "output_groups_expected": 0,
                "output_groups_completed": 0,
                "output_groups_skipped": 0,
                "output_group_skips": [],
            }

        total_predictions = 0
        total_votes = 0
        input_updates_skipped = 0
        output_groups_expected = 0
        output_groups_completed = 0
        output_group_skips: list[dict[str, Any]] = []

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

        if prediction_run_id is not None:
            update_prediction_run_manifest(
                conn,
                run_id=prediction_run_id,
                model_manifest=model_manifest,
                input_manifest={
                    "match_id_filter": match_id,
                    "match_ids": sorted(int(row[0]) for row in match_rows),
                    "markets": sorted(
                        (int(mid), str(play_type))
                        for mid, play_types in available_markets.items()
                        for play_type in play_types
                    ),
                    "predict_time": predict_time,
                },
                provenance_status=run_provenance_status,
            )

        if not available_markets:
            return {
                "status": "ok",
                "predictions": 0,
                "votes": 0,
                "matches_processed": 0,
                "note": "no matches with open official markets",
                "completion_reason": "no_open_markets",
                "output_groups_expected": 0,
                "output_groups_completed": 0,
                "output_groups_skipped": 0,
                "output_group_skips": [],
            }

        for match_row in match_rows:
            mid, home_team_name, away_team_name = (
                match_row[0],
                match_row[1],
                match_row[2],
            )
            play_types = available_markets.get(mid, [])
            for play_type in play_types:
                output_group_counts: dict[str, Any] = {}
                try:
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
                        model_parameters,
                        prediction_run_id=prediction_run_id,
                        model_artifact_identities=model_artifact_identities,
                        output_group_counts=output_group_counts,
                    )
                except InputUpdateSuperseded, LockNotAvailable:
                    # Other matches remain available. Any already committed
                    # options from this calculation are invalidated on reads.
                    conn.rollback()
                    input_updates_skipped += 1
                    skipped_models = output_group_counts.get("expected_models")
                    if skipped_models is None:
                        # If the failure happened before the handicap was
                        # observed, only count models eligible without it.
                        skipped_models = [
                            (model_name, model_version_id)
                            for model_name, model_version_id in active_models.items()
                            if supports_market(model_name, play_type, None)
                        ]
                    derived_counts = output_group_counts.get("derived", {})
                    expected_groups = [
                        (str(play_type), str(model_name), int(model_version_id))
                        for model_name, model_version_id in skipped_models
                    ]
                    expected_groups.extend(
                        (str(derived_play_type), str(model_name), int(model_version_id))
                        for model_name, model_version_id, derived_play_type in derived_counts.get(
                            "expected_models", []
                        )
                    )
                    completed_groups = {
                        (str(play_type), int(model_version_id))
                        for model_version_id in output_group_counts.get(
                            "completed_model_version_ids", []
                        )
                    }
                    completed_groups.update(
                        (str(derived_play_type), int(model_version_id))
                        for _model_name, model_version_id, derived_play_type in derived_counts.get(
                            "completed_groups", []
                        )
                    )
                    existing_skips = output_group_counts.get("skipped", []) + derived_counts.get(
                        "skipped", []
                    )
                    skips_by_key = {
                        (str(item["play_type"]), int(item["model_version_id"])): item
                        for item in existing_skips
                    }
                    output_groups_expected += len(expected_groups)
                    output_groups_completed += len(completed_groups)
                    for expected_play_type, model_name, model_version_id in expected_groups:
                        key = (expected_play_type, model_version_id)
                        if key in completed_groups:
                            continue
                        output_group_skips.append(
                            skips_by_key.get(
                                key,
                                {
                                    "match_id": int(mid),
                                    "model_version_id": model_version_id,
                                    "model_name": model_name,
                                    "play_type": expected_play_type,
                                    "reason": "input_update_unavailable",
                                },
                            )
                        )
                    continue
                total_predictions += p
                total_votes += v
                output_groups_expected += output_group_counts.get("expected", 0)
                output_groups_completed += output_group_counts.get("completed", 0)
                output_group_skips.extend(output_group_counts.get("skipped", []))
                derived_counts = output_group_counts.get("derived", {})
                output_groups_expected += derived_counts.get("expected", 0)
                output_groups_completed += derived_counts.get("completed", 0)
                output_group_skips.extend(derived_counts.get("skipped", []))

    output_group_skips.sort(
        key=lambda item: (
            int(item.get("match_id", 0)),
            str(item.get("play_type", "")),
            int(item.get("model_version_id", 0)),
        )
    )
    output_groups_skipped = max(0, output_groups_expected - output_groups_completed)
    completion_reason = (
        "no_supported_models_for_open_markets"
        if output_groups_expected == 0
        else "expected_output_groups_missing"
        if output_groups_skipped
        else "predictions_completed"
    )

    return {
        "status": "ok",
        "predictions": total_predictions,
        "votes": total_votes,
        "matches_processed": len(match_rows),
        "output_groups_expected": output_groups_expected,
        "output_groups_completed": output_groups_completed,
        "output_groups_skipped": output_groups_skipped,
        "output_group_skips": output_group_skips,
        "completion_reason": completion_reason,
        **({"input_updates_skipped": input_updates_skipped} if input_updates_skipped else {}),
    }


def run(match_id: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Serialize executions before recovering or creating audit/run records."""
    with prediction_execution() as conn:
        if conn is None:
            return {"status": "skipped", "reason": "prediction_execution_in_progress"}
        return _run_owned(conn, match_id=match_id, dry_run=dry_run)


def _run_owned(conn: Any, *, match_id: int | None, dry_run: bool) -> dict[str, Any]:
    run_id = start_tracked_job(
        "model_prediction",
        "model_agent",
        {"dry_run": dry_run, "match_id": match_id, "execution_protocol": EXECUTION_PROTOCOL},
        dependencies=[] if dry_run else ["official_odds_snapshot", "feature_snapshot_build"],
    )
    if dry_run:
        try:
            result = _run_impl(match_id=match_id, dry_run=True)
            finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
            return result
        except Exception as exc:
            finish_tracked_job(run_id, "failed", error=str(exc))
            raise

    prediction_run_id = uuid.uuid4()
    prediction_run_created = False
    prediction_run_finalized = False
    try:
        try:
            code_fingerprint = fingerprint_runtime_sources(_PROJECT_ROOT, _PREDICTION_SOURCE_PATHS)
        except Exception:
            code_fingerprint = {
                "files": {},
                "sha256": None,
                "provenance_status": "incomplete",
                "reason": "runtime_source_fingerprint_unavailable",
            }
        create_prediction_run(
            conn,
            run_id=prediction_run_id,
            ai_job_run_id=run_id,
            release_id=RELEASE_ID,
            code_fingerprint=code_fingerprint,
            model_manifest=[],
            input_manifest={"match_id_filter": match_id},
            provenance_status="incomplete",
        )
        prediction_run_created = True
        result = _run_impl(
            match_id=match_id,
            dry_run=False,
            prediction_run_id=prediction_run_id,
            execution_conn=conn,
        )
        run_status = (
            "failed"
            if result.get("status") == "error"
            else "partial"
            if result.get("input_updates_skipped") or result.get("output_groups_skipped")
            else "completed"
        )
        output_summary = {
            "expected_groups": int(result.get("output_groups_expected", 0)),
            "completed_groups": int(result.get("output_groups_completed", 0)),
            "skipped_groups": int(result.get("output_groups_skipped", 0)),
            "missing_groups": list(result.get("output_group_skips", [])),
            "input_updates_skipped": int(result.get("input_updates_skipped", 0)),
            "completion_reason": str(
                result.get("completion_reason")
                or ("prediction_job_error" if run_status == "failed" else "predictions_completed")
            ),
        }
        finalize_prediction_run(
            conn,
            run_id=prediction_run_id,
            run_status=run_status,
            error_message=result.get("error") if run_status == "failed" else None,
            output_summary=output_summary,
        )
        prediction_run_finalized = True
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        if prediction_run_finalized:
            logger.exception("Prediction output finalized but audit completion failed: %s", run_id)
            raise
        try:
            conn.rollback()
            if prediction_run_created:
                fail_prediction_run(conn, prediction_run_id, str(exc))
        except Exception:
            # Leave the audit running when the business terminal state is
            # unknown (including a lost successful COMMIT acknowledgement).
            # The next owner reconciles both records from persisted facts.
            logger.exception("Prediction run failure finalization failed: %s", prediction_run_id)
        else:
            try:
                finish_tracked_job(run_id, "failed", error=str(exc))
            except Exception:
                logger.exception("Prediction job failure finalization failed: %s", run_id)
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
    model_parameters: dict[str, dict[str, Any]] | None = None,
    prediction_run_id: uuid.UUID | str | None = None,
    model_artifact_identities: dict[str, dict[str, Any]] | None = None,
    output_group_counts: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Run prediction pipeline for a single match + play type.

    Loads odds, runs market_baseline / Poisson / Dixon-Coles / Elo,
    stores predictions and committee votes.

    Returns:
        (predictions_count, votes_count)
    """
    input_fence = capture_prediction_input_fence(conn, mid)
    feature_snapshot = _latest_feature_snapshot(conn, mid, as_of=predict_time)
    feature_snapshot_id = feature_snapshot.get("id") if feature_snapshot else None
    model_parameters = model_parameters or {}
    model_artifact_identities = model_artifact_identities or {}

    def record_expected_groups(
        handicap_value: float | None, *, skipped_reason: str | None = None
    ) -> None:
        if output_group_counts is None or prediction_run_id is None:
            return
        expected_models = [
            (name, int(model_version_id))
            for name, model_version_id in active_models.items()
            if supports_market(name, play_type, handicap_value)
        ]
        output_group_counts["expected"] = len(expected_models)
        output_group_counts["completed"] = 0
        output_group_counts["expected_models"] = expected_models
        output_group_counts["completed_model_version_ids"] = []
        output_group_counts["skipped"] = (
            [
                {
                    "match_id": int(mid),
                    "model_version_id": model_version_id,
                    "model_name": model_name,
                    "play_type": str(play_type),
                    "reason": skipped_reason,
                }
                for model_name, model_version_id in expected_models
            ]
            if skipped_reason
            else []
        )

    # 1. Load latest odds for this play type
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, option_code, sp_value, snapshot_time
            FROM official_odds_snapshots
            WHERE match_id = %s AND play_type = %s
              AND is_open = true
            ORDER BY snapshot_time DESC
            """,
            (mid, play_type),
        )
        odds_rows = cur.fetchall()

    if not odds_rows:
        record_expected_groups(0.0, skipped_reason="official_odds_missing")
        return 0, 0

    odds_dict: dict[str, float] = {}
    snapshot_ids: dict[str, int] = {}
    snapshot_times: dict[str, str] = {}
    for row in odds_rows:
        snap_id, opt, sp, snapshot_time = row
        code = OPTION_MAP.get(opt, opt)
        if code not in odds_dict:
            odds_dict[code] = float(sp)
            snapshot_ids[code] = int(snap_id)
            snapshot_times[code] = (
                snapshot_time.isoformat()
                if hasattr(snapshot_time, "isoformat")
                else str(snapshot_time)
            )

    if not {"3", "1", "0"}.issubset(odds_dict):
        record_expected_groups(0.0, skipped_reason="official_odds_incomplete")
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
            if row and row[0] is not None:
                try:
                    value = float(row[0])
                    if math.isfinite(value) and value.is_integer():
                        handicap = value
                except TypeError, ValueError, OverflowError:
                    pass

    record_expected_groups(handicap)

    # 4. Poisson model
    poisson_matrix = None
    raw_poisson_matrix = None
    dc_matrix = None
    raw_dc_matrix = None
    bivariate_matrix = None
    raw_bivariate_matrix = None
    negative_binomial_matrix = None
    raw_negative_binomial_matrix = None
    feature_adjustment = GoalRateAdjustment(1.3, 1.1, False, 0.0, 1.0, [])
    trained_goal_rates = _load_trained_goal_rates(model_parameters, feature_snapshot)
    poisson_succeeded = False
    dc_succeeded = False
    try:
        if play_type == "rqspf" and (
            trained_goal_rates is None or not supports_market("maher_poisson", play_type, handicap)
        ):
            raise ValueError("handicap score projection requires trained ordinary goal rates")
        if trained_goal_rates:
            raw_lam_h = trained_goal_rates.home_lambda
            raw_lam_a = trained_goal_rates.away_lambda
        else:
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
        poisson_succeeded = True
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

    # Bivariate Poisson preserves the trained Maher marginal rates and adds a
    # fitted shared-goal component. It remains an independently tracked shadow
    # model until its evaluation gates are explicitly promoted.
    trained_bivariate_component = _load_trained_bivariate_shared_component(
        model_parameters, trained_goal_rates if poisson_succeeded else None
    )
    bivariate_is_independent = trained_bivariate_component is not None
    try:
        if trained_bivariate_component is not None:
            raw_bivariate_matrix = bivariate_score_matrix(
                raw_lam_h, raw_lam_a, trained_bivariate_component
            )
            adjusted_component = min(
                trained_bivariate_component,
                min(lam_h, lam_a) * 0.95,
            )
            bivariate_matrix = bivariate_score_matrix(lam_h, lam_a, adjusted_component)
            raw_bivariate_probs = (
                derive_handicap(raw_bivariate_matrix, handicap)
                if play_type == "rqspf" and handicap is not None
                else derive_1x2(raw_bivariate_matrix)
            )
            bivariate_probs = (
                derive_handicap(bivariate_matrix, handicap)
                if play_type == "rqspf" and handicap is not None
                else derive_1x2(bivariate_matrix)
            )
        else:
            raw_bivariate_probs = dict(market_probs)
            bivariate_probs = dict(market_probs)
    except ArithmeticError, ValueError:
        bivariate_is_independent = False
        raw_bivariate_probs = dict(market_probs)
        bivariate_probs = dict(market_probs)

    trained_negative_binomial_dispersion = _load_trained_negative_binomial_dispersion(
        model_parameters, trained_goal_rates if poisson_succeeded else None
    )
    negative_binomial_is_independent = trained_negative_binomial_dispersion is not None
    try:
        if trained_negative_binomial_dispersion is not None:
            raw_negative_binomial_matrix = negative_binomial_score_matrix(
                raw_lam_h, raw_lam_a, trained_negative_binomial_dispersion
            )
            negative_binomial_matrix = negative_binomial_score_matrix(
                lam_h, lam_a, trained_negative_binomial_dispersion
            )
            raw_negative_binomial_probs = (
                derive_handicap(raw_negative_binomial_matrix, handicap)
                if play_type == "rqspf" and handicap is not None
                else derive_1x2(raw_negative_binomial_matrix)
            )
            negative_binomial_probs = (
                derive_handicap(negative_binomial_matrix, handicap)
                if play_type == "rqspf" and handicap is not None
                else derive_1x2(negative_binomial_matrix)
            )
        else:
            raw_negative_binomial_probs = dict(market_probs)
            negative_binomial_probs = dict(market_probs)
    except ArithmeticError, ValueError:
        negative_binomial_is_independent = False
        raw_negative_binomial_probs = dict(market_probs)
        negative_binomial_probs = dict(market_probs)

    # 5. Dixon-Coles model
    try:
        if not poisson_succeeded:
            raise ValueError("ordinary goal rates unavailable")
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
        dc_succeeded = True
    except Exception:
        raw_dc_probs = dict(raw_poisson_probs)
        dc_probs = dict(poisson_probs)
        raw_dc_matrix = raw_poisson_matrix
        dc_matrix = poisson_matrix

    # 5b. Derive BF/ZJQ/BQC from SPF score matrix
    derived_predictions = 0
    if play_type == "spf" and poisson_matrix and raw_poisson_matrix:
        derived_predictions = store_derived_play_predictions(
            input_fence=input_fence,
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
            model_independence={
                "market_baseline": False,
                "maher_poisson": trained_goal_rates is not None and poisson_succeeded,
                "dixon_coles": trained_goal_rates is not None
                and mle_rho is not None
                and dc_succeeded,
            },
            rollout_modes={
                name: str(p.get("rollout_mode") or "live") for name, p in model_parameters.items()
            },
            prediction_run_id=str(prediction_run_id) if prediction_run_id is not None else None,
            model_artifact_identities=model_artifact_identities,
            output_group_counts=output_group_counts,
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

    # 6. Glicko-2 applies a stronger data-quality threshold than Elo because
    # it exposes rating uncertainty. An unavailable state remains a benchmark,
    # never an independent committee vote.
    try:
        trained_glicko2 = _load_trained_glicko2_probabilities(conn, feature_snapshot)
        glicko2_is_independent = trained_glicko2 is not None
        glicko2_1x2 = trained_glicko2 or dict(market_probs)
    except Exception:
        glicko2_is_independent = False
        glicko2_1x2 = dict(market_probs)

    # XGBoost is trained solely from pre-kickoff feature snapshots and must
    # carry a persisted temporal-validation profile. It stays shadow-only even
    # when that profile is available.
    try:
        trained_xgboost = _load_xgboost_shadow_probabilities(model_parameters, feature_snapshot)
        xgboost_is_independent = trained_xgboost is not None
        xgboost_1x2 = trained_xgboost or dict(market_probs)
    except Exception:
        xgboost_is_independent = False
        xgboost_1x2 = dict(market_probs)

    # Logistic regression is the transparent counterpart to the nonlinear
    # feature model. It remains shadow-only even when its profile is valid.
    try:
        trained_logistic = _load_logistic_shadow_probabilities(model_parameters, feature_snapshot)
        logistic_is_independent = trained_logistic is not None
        logistic_1x2 = trained_logistic or dict(market_probs)
    except Exception:
        logistic_is_independent = False
        logistic_1x2 = dict(market_probs)

    try:
        trained_random_forest = _load_random_forest_shadow_probabilities(
            model_parameters, feature_snapshot
        )
        random_forest_is_independent = trained_random_forest is not None
        random_forest_1x2 = trained_random_forest or dict(market_probs)
    except Exception:
        random_forest_is_independent = False
        random_forest_1x2 = dict(market_probs)

    try:
        trained_extra_trees = _load_extra_trees_shadow_probabilities(
            model_parameters, feature_snapshot
        )
        extra_trees_is_independent = trained_extra_trees is not None
        extra_trees_1x2 = trained_extra_trees or dict(market_probs)
    except Exception:
        extra_trees_is_independent = False
        extra_trees_1x2 = dict(market_probs)

    try:
        trained_hist_gradient_boosting = _load_hist_gradient_boosting_shadow_probabilities(
            model_parameters, feature_snapshot
        )
        hist_gradient_boosting_is_independent = trained_hist_gradient_boosting is not None
        hist_gradient_boosting_1x2 = trained_hist_gradient_boosting or dict(market_probs)
    except Exception:
        hist_gradient_boosting_is_independent = False
        hist_gradient_boosting_1x2 = dict(market_probs)

    try:
        trained_adaboost = _load_adaboost_shadow_probabilities(model_parameters, feature_snapshot)
        adaboost_is_independent = trained_adaboost is not None
        adaboost_1x2 = trained_adaboost or dict(market_probs)
    except Exception:
        adaboost_is_independent = False
        adaboost_1x2 = dict(market_probs)

    try:
        trained_lda = _load_lda_shadow_probabilities(model_parameters, feature_snapshot)
        lda_is_independent = trained_lda is not None
        lda_1x2 = trained_lda or dict(market_probs)
    except Exception:
        lda_is_independent = False
        lda_1x2 = dict(market_probs)

    try:
        trained_knn = _load_knn_shadow_probabilities(model_parameters, feature_snapshot)
        knn_is_independent = trained_knn is not None
        knn_1x2 = trained_knn or dict(market_probs)
    except Exception:
        knn_is_independent = False
        knn_1x2 = dict(market_probs)
    try:
        trained_mlp = _load_mlp_shadow_probabilities(model_parameters, feature_snapshot)
        mlp_is_independent, mlp_1x2 = trained_mlp is not None, trained_mlp or dict(market_probs)
    except Exception:
        mlp_is_independent, mlp_1x2 = False, dict(market_probs)

    try:
        trained_naive_bayes = _load_naive_bayes_shadow_probabilities(
            model_parameters, feature_snapshot
        )
        naive_bayes_is_independent = trained_naive_bayes is not None
        naive_bayes_1x2 = trained_naive_bayes or dict(market_probs)
    except Exception:
        naive_bayes_is_independent = False
        naive_bayes_1x2 = dict(market_probs)

    try:
        trained_svm = _load_svm_shadow_probabilities(model_parameters, feature_snapshot or {})
        svm_is_independent = trained_svm is not None
        svm_1x2 = trained_svm or dict(market_probs)
    except Exception:
        svm_is_independent = False
        svm_1x2 = dict(market_probs)

    try:
        trained_bayesian_form = _load_bayesian_form_probabilities(conn, mid, feature_snapshot)
        bayesian_form_is_independent = trained_bayesian_form is not None
        bayesian_form_1x2 = trained_bayesian_form or dict(market_probs)
    except Exception:
        bayesian_form_is_independent = False
        bayesian_form_1x2 = dict(market_probs)

    rollout_modes = {
        name: str(parameters.get("rollout_mode") or "live")
        for name, parameters in model_parameters.items()
    }

    # 7. Write predictions per model
    model_results = {
        "market_baseline": (market_probs, market_probs),
        "maher_poisson": (raw_poisson_probs, poisson_probs),
        "dixon_coles": (raw_dc_probs, dc_probs),
        "elo_rating": (elo_1x2, elo_1x2),
        "glicko2_rating": (glicko2_1x2, glicko2_1x2),
        "bivariate_poisson": (raw_bivariate_probs, bivariate_probs),
        "negative_binomial_shadow": (raw_negative_binomial_probs, negative_binomial_probs),
        "xgboost_shadow": (xgboost_1x2, xgboost_1x2),
        "logistic_shadow": (logistic_1x2, logistic_1x2),
        "bayesian_form": (bayesian_form_1x2, bayesian_form_1x2),
        "random_forest_shadow": (random_forest_1x2, random_forest_1x2),
        "extra_trees_shadow": (extra_trees_1x2, extra_trees_1x2),
        "hist_gradient_boosting_shadow": (hist_gradient_boosting_1x2, hist_gradient_boosting_1x2),
        "adaboost_shadow": (adaboost_1x2, adaboost_1x2),
        "lda_shadow": (lda_1x2, lda_1x2),
        "knn_shadow": (knn_1x2, knn_1x2),
        "mlp_shadow": (mlp_1x2, mlp_1x2),
        "naive_bayes_shadow": (naive_bayes_1x2, naive_bayes_1x2),
        "svm_shadow": (svm_1x2, svm_1x2),
    }
    model_independence = {
        "market_baseline": False,
        "maher_poisson": trained_goal_rates is not None and poisson_succeeded,
        "dixon_coles": trained_goal_rates is not None and mle_rho is not None and dc_succeeded,
        "elo_rating": elo_is_independent,
        "glicko2_rating": glicko2_is_independent,
        "bivariate_poisson": bivariate_is_independent,
        "negative_binomial_shadow": negative_binomial_is_independent,
        "xgboost_shadow": xgboost_is_independent,
        "logistic_shadow": logistic_is_independent,
        "bayesian_form": bayesian_form_is_independent,
        "random_forest_shadow": random_forest_is_independent,
        "extra_trees_shadow": extra_trees_is_independent,
        "hist_gradient_boosting_shadow": hist_gradient_boosting_is_independent,
        "adaboost_shadow": adaboost_is_independent,
        "lda_shadow": lda_is_independent,
        "knn_shadow": knn_is_independent,
        "mlp_shadow": mlp_is_independent,
        "naive_bayes_shadow": naive_bayes_is_independent,
        "svm_shadow": svm_is_independent,
    }

    total_p = derived_predictions
    total_v = 0

    # Validate all eligible models before computing any cross-model diagnostic.
    # Unsupported markets have no prediction row, rather than mislabelled 1X2 odds.
    validated_metrics = {}
    for name, (_raw, distribution) in model_results.items():
        if name not in active_models or not supports_market(name, play_type, handicap):
            continue
        try:
            validated_metrics[name] = validate_market(
                model_probabilities=distribution,
                market_probabilities=market_probs,
                odds_by_option=odds_dict,
                snapshot_ids=snapshot_ids,
            )
        except MarketMetricValidationError:
            model_version_id = active_models.get(name)
            if (
                prediction_run_id is not None
                and output_group_counts is not None
                and model_version_id is not None
                and supports_market(name, play_type, handicap)
            ):
                output_group_counts.setdefault("skipped", []).append(
                    {
                        "match_id": int(mid),
                        "model_version_id": int(model_version_id),
                        "model_name": name,
                        "play_type": str(play_type),
                        "reason": "market_validation_failed",
                    }
                )
            continue

    vote_weights = committee_weights(
        active_models, model_independence, rollout_modes, set(validated_metrics)
    )
    for model_name, (raw_probs, probs) in model_results.items():
        mv_id = active_models.get(model_name)
        if mv_id is None or model_name not in validated_metrics:
            continue
        option_metrics = validated_metrics[model_name]
        goal_family = MODEL_FAMILIES.get(model_name) == "maher_goal_rates"
        score_source_used = goal_family and (
            poisson_succeeded
            if model_name in ("maher_poisson", "dixon_coles")
            else model_independence[model_name]
        )
        trained_rate_source = trained_goal_rates if score_source_used else None

        group_predictions: list[dict[str, Any]] = []
        for opt_code in ("3", "1", "0"):
            model_p = probs.get(opt_code, 0.0)
            raw_model_p = raw_probs.get(opt_code, model_p)
            market_p = market_probs.get(opt_code, 0.0)

            fair_odds = _safe_fair_odds(model_p)
            metric = option_metrics[opt_code]
            stored_model_p = round(model_p, 6)
            stored_market_p = round(market_p, 6)
            stored_break_even = round(metric.break_even_probability, 6)

            diagnostic = disagreement_diagnostic(
                {name: result[1] for name, result in model_results.items()},
                active_models,
                model_independence,
                rollout_modes,
                set(validated_metrics),
                opt_code,
            )
            uncertainty = diagnostic["model_std"]

            pred: dict[str, Any] = {
                "input_fence": input_fence,
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
                "probability_lower_bound": None,
                "probability_upper_bound": None,
                "uncertainty_score": uncertainty,
                "adjusted_probability": round(model_p, 6),
                "fair_odds": fair_odds,
                "ev": round(stored_model_p * odds_dict[opt_code] - 1.0, 6),
                "break_even_probability": stored_break_even,
                "market_edge": round(stored_model_p - stored_market_p, 6),
                "breakeven_edge": round(stored_model_p - stored_break_even, 6),
                "validation_status": "valid",
                "validation_errors": [],
                "calculation_version": "market_metrics_v2",
                "confidence_score": None,
                "risk_score": None,
                "uncertainty_reason": {
                    "model_std": uncertainty,
                    "disagreement": diagnostic,
                    "confidence_status": "uncalibrated",
                    "interval_status": "not_estimated",
                    "risk_status": "not_estimated",
                    "signal_kind": "market_baseline"
                    if model_name == "market_baseline"
                    else "independent_signal"
                    if model_independence[model_name]
                    else "non_independent_score_projection"
                    if score_source_used
                    else "market_fallback",
                    "model_capability": play_type,
                    "handicap": handicap if play_type == "rqspf" else None,
                    "rho": rho if model_name == "dixon_coles" else None,
                    "rho_source": "mle"
                    if (model_name == "dixon_coles" and mle_rho is not None)
                    else "default",
                    "margin_removal": (
                        "not_applicable"
                        if trained_rate_source is not None
                        or (not goal_family and model_independence[model_name])
                        else "shin_flb"
                        if score_source_used
                        else "proportional"
                    ),
                    "goal_rate_source": "trained_maher"
                    if trained_rate_source is not None
                    else "official_market"
                    if goal_family or model_name == "market_baseline"
                    else None,
                    "training_matches": trained_rate_source.training_matches
                    if trained_rate_source is not None
                    else model_parameters.get(model_name, {}).get("training_matches"),
                    "minimum_team_matches": trained_rate_source.minimum_team_matches
                    if trained_rate_source is not None
                    else None,
                    "elo_based": model_name == "elo_rating",
                    "glicko2_based": model_name == "glicko2_rating",
                    "bivariate_poisson_based": model_name == "bivariate_poisson",
                    "negative_binomial_shadow_based": model_name == "negative_binomial_shadow",
                    "xgboost_shadow_based": model_name == "xgboost_shadow",
                    "logistic_shadow_based": model_name == "logistic_shadow",
                    "bayesian_form_based": model_name == "bayesian_form",
                    "random_forest_shadow_based": model_name == "random_forest_shadow",
                    "extra_trees_shadow_based": model_name == "extra_trees_shadow",
                    "hist_gradient_boosting_shadow_based": model_name
                    == "hist_gradient_boosting_shadow",
                    "adaboost_shadow_based": model_name == "adaboost_shadow",
                    "lda_shadow_based": model_name == "lda_shadow",
                    "knn_shadow_based": model_name == "knn_shadow",
                    "mlp_shadow_based": model_name == "mlp_shadow",
                    "naive_bayes_shadow_based": model_name == "naive_bayes_shadow",
                    "svm_shadow_based": model_name == "svm_shadow",
                    "rollout_mode": rollout_modes.get(model_name, "live"),
                    "model_independent": model_independence[model_name],
                    "feature_adjustment": {
                        "version": feature_adjustment.version,
                        "applied": feature_adjustment.applied and score_source_used,
                        "snapshot_id": feature_snapshot_id,
                        "home_log_shift": feature_adjustment.home_log_shift,
                        "total_goal_multiplier": feature_adjustment.total_goal_multiplier,
                        "reasons": feature_adjustment.reasons,
                    },
                },
            }
            if prediction_run_id is None:
                store_model_prediction(conn, pred)
                total_p += 1
            else:
                group_predictions.append(pred)

        if prediction_run_id is not None and group_predictions:
            identity = model_artifact_identities.get(model_name)
            score_matrices = {
                "maher_poisson": (raw_poisson_matrix, poisson_matrix),
                "dixon_coles": (raw_dc_matrix, dc_matrix),
                "bivariate_poisson": (raw_bivariate_matrix, bivariate_matrix),
                "negative_binomial_shadow": (
                    raw_negative_binomial_matrix,
                    negative_binomial_matrix,
                ),
            }
            raw_matrix, adjusted_matrix = score_matrices.get(model_name, (None, None))
            input_payload = input_fence.payload() if input_fence is not None else None
            store_prediction_group(
                conn,
                run_id=prediction_run_id,
                metadata={
                    "match_id": mid,
                    "model_version_id": mv_id,
                    "play_type": play_type,
                    "market_variant": f"handicap={handicap}" if handicap is not None else "",
                    "predict_time": predict_time,
                    "expected_options": ["3", "1", "0"],
                    "odds_snapshot_ids": snapshot_ids,
                    "odds_snapshot_times": snapshot_times,
                    "feature_snapshot_id": feature_snapshot_id,
                    "input_fence": input_payload,
                    "score_matrix": (
                        {"raw": raw_matrix, "adjusted": adjusted_matrix}
                        if adjusted_matrix is not None
                        else None
                    ),
                    "artifact_identity": identity,
                    "provenance_status": (
                        identity.get("provenance_status", "incomplete")
                        if identity
                        else "incomplete"
                    ),
                },
                predictions=group_predictions,
            )
            if output_group_counts is not None:
                output_group_counts["completed"] = output_group_counts.get("completed", 0) + 1
                output_group_counts.setdefault("completed_model_version_ids", []).append(int(mv_id))
            total_p += len(group_predictions)

        # Committee votes represent independent model opinions. Market-seeded
        # fallbacks remain available as benchmark predictions but must never
        # enter committee or recommendation decision paths.
        if model_name not in vote_weights:
            continue

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
                "vote_weight": vote_weights[model_name],
            }
            store_committee_vote(conn, vote)
            total_v += 1

    if output_group_counts is not None and prediction_run_id is not None:
        completed_ids = set(output_group_counts.get("completed_model_version_ids", []))
        skipped_ids = {
            int(item["model_version_id"]) for item in output_group_counts.get("skipped", [])
        }
        for model_name, model_version_id in output_group_counts.get("expected_models", []):
            if model_version_id not in completed_ids and model_version_id not in skipped_ids:
                output_group_counts.setdefault("skipped", []).append(
                    {
                        "match_id": int(mid),
                        "model_version_id": model_version_id,
                        "model_name": model_name,
                        "play_type": str(play_type),
                        "reason": "model_output_not_published",
                    }
                )

    return total_p, total_v


if __name__ == "__main__":
    import sys

    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dry = "--dry-run" in sys.argv
    result = run(match_id=mid, dry_run=dry)
    print(result)
