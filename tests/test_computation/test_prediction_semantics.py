"""Local fixed evidence for versioned semantics and honest model diagnostics."""

import json
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from scripts import feature_importance, prematch_feature_dataset, shadow_model_helpers
from scripts.jobs import run_feature_snapshot_build as build
from scripts.jobs import run_model_prediction as prediction

CURRENT_SNAPSHOT = "v4_observed_form"
CURRENT_SCHEMA = "observed-form/v2"
LEGACY_SCHEMA = "legacy-enriched/v1"


def build_snapshot(forms):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(101,)]
    cursor.fetchone.return_value = (101, "home", "away", "league", datetime(2026, 10, 17, 20), {})
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(build, "get_db")
        ).return_value.__enter__.return_value = conn
        for name, value in {
            "_business_now_naive": datetime(2026, 10, 17, 10),
            "_resolve_competition_season_id": 3,
            "_resolve_match_stadium_id": None,
            "compute_rest_days": 3,
            "_load_collected_weather": ({}, False),
            "load_pre_kickoff_upset_risk": {},
            "_load_latest_open_odds": [
                {"play_type": "spf", "option_code": c, "sp_value": v}
                for c, v in [("h", 2), ("d", 3), ("a", 4)]
            ],
        }.items():
            stack.enter_context(patch.object(build, name, return_value=value))
        stack.enter_context(patch.object(build, "_resolve_team_id", side_effect=[10, 20]))
        stack.enter_context(patch.object(build, "compute_team_form", side_effect=forms))
        stack.enter_context(patch.object(build, "store_team_season_profile"))
        store = stack.enter_context(
            patch.object(build, "store_match_feature_snapshot", return_value=88)
        )
        for module, name in (
            ("build_lineup_strength", "build_lineup_features"),
            ("build_injury_impact", "build_injury_features"),
            ("build_travel_features", "build_travel_features"),
            ("build_motivation_score", "build_motivation_features"),
            ("build_tournament_incentive", "build_tournament_incentive_features"),
        ):
            stack.enter_context(patch(f"scripts.features.{module}.{name}", return_value={}))
        result = build._run_impl(match_id=101)
    assert result["snapshots_built"] == 1
    return store.call_args.args[1]


def test_new_snapshot_records_observed_form_and_never_fake_market_values():
    snapshot = build_snapshot(
        [
            {"matches_played": 5, "goals_for": 0, "goals_against": 8},
            {"matches_played": 4, "goals_for": 6, "goals_against": 0},
        ]
    )
    assert snapshot["feature_version"] == CURRENT_SNAPSHOT
    for name in ("home_team_market_value", "away_team_market_value", "team_market_value_ratio"):
        assert snapshot[name] is None
    assert snapshot["home_attack_strength_score"] == 0
    assert snapshot["home_defense_strength_score"] == 1.6
    assert snapshot["away_attack_strength_score"] == 1.5
    assert snapshot["away_defense_strength_score"] == 0
    refs = snapshot["raw_feature_refs"]
    assert refs["feature_schema_version"] == CURRENT_SCHEMA
    assert refs["team_form"]["home"]["matches_played"] == 5
    assert refs["odds_implied"]["home_win_prob"] > 0
    assert "football-data.org" not in refs["enrichment_sources"]


def test_missing_form_remains_missing_without_stopping_optional_data_pipeline():
    snapshot = build_snapshot([{"matches_played": 0}, {"matches_played": 0}])
    for side in ("home", "away"):
        assert snapshot[f"{side}_attack_strength_score"] is None
        assert snapshot[f"{side}_defense_strength_score"] is None


@pytest.mark.parametrize(
    "schema,version,allowed",
    [
        (CURRENT_SCHEMA, CURRENT_SNAPSHOT, True),
        (LEGACY_SCHEMA, "v3_upset_risk", True),
        (LEGACY_SCHEMA, CURRENT_SNAPSHOT, False),
        (CURRENT_SCHEMA, "v3_upset_risk", False),
        ("unknown", CURRENT_SNAPSHOT, False),
    ],
)
def test_artifact_semantics_never_cross_version_boundary(schema, version, allowed):
    params = {
        "feature_schema_version": schema,
        "feature_input_policy": "snapshot-columns/v1",
        "feature_columns": ["home_attack_strength_score"],
    }
    actual = shadow_model_helpers.prepare_shadow_input(
        params, {"feature_version": version, "home_attack_strength_score": 1.5}
    )
    assert (actual is not None) is allowed


def test_training_and_explanation_only_select_current_semantics(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    assert prematch_feature_dataset.load_settled_pre_kickoff_dataset(conn) is None
    assert cursor.execute.call_args.args[1]["feature_versions"] == (CURRENT_SNAPSHOT,)
    assert feature_importance._load_training_data(conn, min_samples=1) is None
    sql, params = cursor.execute.call_args.args
    assert "fs.feature_version IN %(feature_versions)s" in sql
    assert params["feature_versions"] == (CURRENT_SNAPSHOT,)
    assert "r.result_status IN ('final', 'confirmed')" in sql
    monkeypatch.setattr(feature_importance, "train_if_needed", lambda _: {"status": "ok"})
    cursor.fetchone.return_value = None
    assert feature_importance.explain_prediction(conn, 101)["status"] == "error"
    sql, params = cursor.execute.call_args.args
    assert "fs.feature_version IN %(feature_versions)s" in sql
    assert params["feature_versions"] == (CURRENT_SNAPSHOT,)
    assert "fs.id DESC" in sql


def test_feature_labels_describe_measurement_instead_of_market_proxy():
    labels = feature_importance.FEATURE_LABELS
    assert "概率" not in labels["home_team_market_value"]
    assert "场均进球" in labels["home_attack_strength_score"]
    assert "场均失球" in labels["home_defense_strength_score"]


def predict(
    monkeypatch,
    active,
    *,
    play="spf",
    handicap=None,
    rates=None,
    bad_poisson=False,
    bad_dc=False,
    parameters=None,
):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(11, "h", 2), (12, "d", 3), (13, "a", 4)]
    cursor.fetchone.return_value = None if handicap is None else (handicap,)
    monkeypatch.setattr(prediction, "_latest_feature_snapshot", lambda *a, **k: {"id": 88})
    monkeypatch.setattr(prediction, "store_derived_play_predictions", lambda **k: 0)
    monkeypatch.setattr(prediction, "_load_trained_goal_rates", lambda *a: rates)
    for name in dir(prediction):
        if name.startswith("_load_") and name.endswith("probabilities"):
            monkeypatch.setattr(prediction, name, lambda *a: {"3": 0.6, "1": 0.25, "0": 0.15})
    store, vote = Mock(), Mock()
    monkeypatch.setattr(prediction, "store_model_prediction", store)
    monkeypatch.setattr(prediction, "store_committee_vote", vote)
    if bad_poisson:
        monkeypatch.setattr(prediction, "score_matrix", Mock(side_effect=ValueError("fixture")))
    if bad_dc:
        monkeypatch.setattr(
            prediction, "dixon_coles_matrix", Mock(side_effect=ValueError("fixture"))
        )
    counts = prediction._predict_match_play_type(
        conn, 101, "home", "away", play, active, -0.08, -0.08, "2026-10-17T10:00:00", parameters
    )
    return counts, [c.args[1] for c in store.call_args_list], vote


@pytest.mark.parametrize(
    "model",
    [
        "elo_rating",
        "glicko2_rating",
        "bayesian_form",
        "logistic_shadow",
        "xgboost_shadow",
        "random_forest_shadow",
        "extra_trees_shadow",
        "hist_gradient_boosting_shadow",
        "adaboost_shadow",
        "lda_shadow",
        "knn_shadow",
        "mlp_shadow",
        "naive_bayes_shadow",
        "svm_shadow",
    ],
)
def test_ordinary_1x2_models_never_publish_handicap_predictions(monkeypatch, model):
    count, stored, vote = predict(monkeypatch, {model: 1}, play="rqspf", handicap=-1)
    assert count == (0, 0)
    assert stored == []
    vote.assert_not_called()


@pytest.mark.parametrize("handicap", [None, float("nan"), float("inf"), 0.5, "invalid"])
def test_unusable_handicap_only_allows_market_baseline(monkeypatch, handicap):
    count, stored, vote = predict(
        monkeypatch,
        {"market_baseline": 1, "maher_poisson": 2, "dixon_coles": 3},
        play="rqspf",
        handicap=handicap,
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    assert count == (3, 0)
    assert {s["model_version_id"] for s in stored} == {1}
    assert all(s["uncertainty_reason"]["handicap"] is None for s in stored)
    json.dumps(stored, allow_nan=False)
    vote.assert_not_called()


def test_zero_handicap_is_real_and_trained_score_model_is_supported(monkeypatch):
    _, stored, _ = predict(
        monkeypatch,
        {"maher_poisson": 2},
        play="rqspf",
        handicap=0,
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    assert len(stored) == 3
    assert all(s["uncertainty_reason"]["model_independent"] for s in stored)
    assert all(s["uncertainty_reason"]["handicap"] == 0 for s in stored)


def test_untrained_handicap_cannot_invert_handicap_odds_as_ordinary_score_rates(monkeypatch):
    _, stored, vote = predict(monkeypatch, {"maher_poisson": 2}, play="rqspf", handicap=-1)
    assert len(stored) == 3
    assert all(s["model_probability"] == s["market_probability"] for s in stored)
    assert all(not s["uncertainty_reason"]["model_independent"] for s in stored)
    vote.assert_not_called()


@pytest.mark.parametrize("bad_poisson,bad_dc", [(True, False), (False, True)])
def test_failed_goal_model_never_retains_independent_vote(monkeypatch, bad_poisson, bad_dc):
    _, stored, vote = predict(
        monkeypatch,
        {"dixon_coles" if bad_dc else "maher_poisson": 2},
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
        bad_poisson=bad_poisson,
        bad_dc=bad_dc,
    )
    assert all(not s["uncertainty_reason"]["model_independent"] for s in stored)
    if bad_poisson:
        assert all(s["uncertainty_reason"]["goal_rate_source"] == "official_market" for s in stored)
    vote.assert_not_called()


@pytest.mark.parametrize(
    "model,params",
    [
        ("bivariate_poisson", {"converged": True, "n_matches": 200, "shared_goal_component": 0.1}),
        ("negative_binomial_shadow", {"converged": True, "n_matches": 200, "dispersion": 0.5}),
    ],
)
def test_goal_variants_report_their_actual_shared_trained_rate_source(monkeypatch, model, params):
    _, rows, _ = predict(
        monkeypatch,
        {model: 1},
        parameters={model: params},
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    assert len(rows) == 3
    assert all(r["uncertainty_reason"]["goal_rate_source"] == "trained_maher" for r in rows)


def test_rating_signal_does_not_claim_another_models_training_metadata(monkeypatch):
    _, rows, _ = predict(
        monkeypatch,
        {"elo_rating": 1},
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    assert all(r["uncertainty_reason"]["goal_rate_source"] is None for r in rows)
    assert all(r["uncertainty_reason"]["training_matches"] is None for r in rows)


def test_uncalibrated_confidence_intervals_and_risk_are_unknown(monkeypatch):
    _, stored, _ = predict(monkeypatch, {"market_baseline": 1})
    assert len(stored) == 3
    for s in stored:
        for key in (
            "confidence_score",
            "risk_score",
            "probability_lower_bound",
            "probability_upper_bound",
            "uncertainty_score",
        ):
            assert s[key] is None
        assert s["uncertainty_reason"]["confidence_status"] == "uncalibrated"


def test_disagreement_ignores_inactive_shadow_fallback_invalid_and_same_source_multiplicity():
    from scripts.model_signal_policy import disagreement_diagnostic

    distributions = {
        "maher_poisson": {"3": 0.6},
        "dixon_coles": {"3": 0.6},
        "elo_rating": {"3": 0.2},
        "glicko2_rating": {"3": 0.2},
        "market_baseline": {"3": 0.99},
        "logistic_shadow": {"3": 0.99},
        "random_forest_shadow": {"3": 0.99},
        "bayesian_form": {"3": 0.99},
    }
    active = {n: i for i, n in enumerate(distributions, 1) if n != "bayesian_form"}
    independent = dict.fromkeys(distributions, True)
    independent["random_forest_shadow"] = False
    result = disagreement_diagnostic(
        distributions,
        active,
        independent,
        {"logistic_shadow": "shadow"},
        set(distributions) - {"glicko2_rating"},
        "3",
    )
    assert result["model_std"] == pytest.approx(0.2)
    assert result["family_count"] == 2
    assert set(result["models"]) == {"maher_poisson", "dixon_coles", "elo_rating"}
    assert result["kind"] == "family_disagreement_not_confidence"


@pytest.mark.parametrize("names", [[], ["maher_poisson"], ["maher_poisson", "dixon_coles"]])
def test_fewer_than_two_source_families_has_no_measured_disagreement(names):
    from scripts.model_signal_policy import disagreement_diagnostic

    result = disagreement_diagnostic(
        {n: {"3": 0.6} for n in names},
        dict.fromkeys(names, 1),
        dict.fromkeys(names, True),
        {},
        set(names),
        "3",
    )
    assert result["model_std"] is None


def test_pipeline_diagnostic_excludes_valid_but_shadow_classifier(monkeypatch):
    _, stored, _ = predict(
        monkeypatch,
        {"elo_rating": 1, "glicko2_rating": 2, "logistic_shadow": 3},
        parameters={"logistic_shadow": {"rollout_mode": "shadow"}},
    )
    assert len(stored) == 9
    assert all(s["uncertainty_score"] is None for s in stored)
    assert all(s["uncertainty_reason"]["disagreement"]["family_count"] == 1 for s in stored)


def test_same_source_committee_models_share_one_family_weight(monkeypatch):
    counts, _, vote = predict(
        monkeypatch,
        {"maher_poisson": 1, "dixon_coles": 2, "elo_rating": 3, "glicko2_rating": 4},
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    assert counts == (12, 12)
    rows = [call.args[1] for call in vote.call_args_list]
    assert all(row["vote_weight"] == 0.5 for row in rows)
    for code in ("3", "1", "0"):
        assert sum(r["vote_weight"] for r in rows if r["option_code"] == code) == 2


@pytest.mark.parametrize("handicap", [-1, 0, 1])
def test_trained_handicap_projection_uses_the_real_score_distribution(monkeypatch, handicap):
    from scripts.poisson_model import derive_handicap, score_matrix

    _, rows, _ = predict(
        monkeypatch,
        {"maher_poisson": 2},
        play="rqspf",
        handicap=handicap,
        rates=SimpleNamespace(
            home_lambda=1.7, away_lambda=0.9, training_matches=100, minimum_team_matches=10
        ),
    )
    expected = derive_handicap(score_matrix(1.7, 0.9), float(handicap))
    assert len(rows) == 3
    assert sum(row["model_probability"] for row in rows) == pytest.approx(1, abs=2e-6)
    assert {row["option_code"]: row["model_probability"] for row in rows} == {
        code: round(value, 6) for code, value in expected.items()
    }


def test_real_prediction_storage_preserves_unknown_confidence(monkeypatch):
    from scripts.model_storage import store_model_prediction

    _, rows, _ = predict(monkeypatch, {"market_baseline": 1})
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (7,)
    assert store_model_prediction(conn, rows[0]) == 7
    params = cursor.execute.call_args.args[1]
    assert params["confidence_score"] is None
    assert params["risk_score"] is None
    assert params["probability_lower_bound"] is None
    assert json.loads(params["uncertainty_reason"])["confidence_status"] == "uncalibrated"


def test_prediction_api_preserves_null_confidence_without_breaking_page(client):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (
            1,
            101,
            datetime(2026, 10, 17, 10),
            "market_baseline",
            "spf",
            "3",
            0.4,
            0.4,
            0.4,
            2.5,
            -0.2,
            None,
            "home",
            "away",
            *([None] * 10),
        )
    ]
    with patch("apps.backend.src.routers.predictions.get_db") as db:
        db.return_value.__enter__.return_value = conn
        response = client.get("/api/predictions?include_summary=false")
    assert response.status_code == 200
    assert response.json()["predictions"][0]["confidence"] is None


@pytest.mark.parametrize("confidence", [None, 0.0])
def test_recommendation_item_preserves_unknown_vs_real_zero(confidence):
    from scripts.jobs.run_recommendation_candidate import _make_item, _parse_candidates

    row = (
        1,
        101,
        2,
        "spf",
        "3",
        0.6,
        0.5,
        0.1,
        confidence,
        None,
        11,
        88,
        "home",
        "away",
        "league",
        datetime(2026, 10, 17, 20),
        2,
        "maher_poisson",
    )
    parsed = _parse_candidates([row], {88: 80}, {(101, "spf"): True})
    assert len(parsed) == 1
    assert parsed[0]["confidence_score"] == confidence
    assert parsed[0]["risk_score"] is None
    assert _make_item(parsed[0])["confidence_score"] == confidence


@pytest.mark.parametrize("confidence", [None, 0.0])
def test_live_recommendation_api_keeps_unknown_and_real_zero_distinct(client, confidence):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (
            1,
            101,
            "spf",
            "3",
            0.6,
            0.5,
            1.6667,
            0.2,
            confidence,
            datetime(2026, 10, 17, 10),
            "maher_poisson",
            "home",
            "away",
            "league",
            datetime(2026, 10, 17, 20),
            "scheduled",
            None,
            "1001",
            2,
            datetime(2026, 10, 17, 10),
            80,
            "agent_virtual_recommendation",
            "reference",
        )
    ]
    with patch("apps.backend.src.routers.predictions.get_db") as db:
        db.return_value.__enter__.return_value = conn
        response = client.get("/api/recommendations/live?min_confidence=0")
    assert response.status_code == 200
    assert response.json()["recommendations"][0]["confidence"] == confidence
    sql = " ".join(cursor.execute.call_args.args[0].split())
    assert "%(min_confidence)s <= 0 OR sti.confidence_score >= %(min_confidence)s" in sql
