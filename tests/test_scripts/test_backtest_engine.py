from dataclasses import replace
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scripts.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BetRecord,
    ResearchEvaluationConfig,
    ResearchMatch,
    build_research_time_splits,
    evaluate_research_reconstruction,
    run_backtest_from_config,
)
from scripts.training_manifest import CandidateMatch


def _settled_row(option_code: str, probability: float, ev: float) -> dict:
    return {
        "match_id": 101,
        "match_date": "2026-07-10",
        "model_name": "elo_rating",
        "play_type": "spf",
        "option_code": option_code,
        "model_probability": probability,
        "market_probability": 0.33,
        "sp_value": 3.0,
        "ev": ev,
        "confidence_score": 0.8,
        "actual_result": "3",
    }


def test_backtest_query_uses_latest_prediction_run_and_asof_odds() -> None:
    engine = BacktestEngine(object(), BacktestConfig())

    sql, _params = engine._build_query()
    normalized = " ".join(sql.split())

    assert "DENSE_RANK() OVER" in normalized
    assert "prediction_rank = 1" in normalized
    assert "oos.snapshot_time <= mp.predict_time" in normalized
    assert "source_mp.validation_status = 'valid'" in normalized
    assert "model_independent" in normalized
    assert "CASE WHEN mp.play_type IN ('spf', 'rqspf') THEN CASE mp.option_code" in normalized


def test_backtest_query_maps_each_play_type_to_its_own_result() -> None:
    engine = BacktestEngine(object(), BacktestConfig())

    sql, _params = engine._build_query()
    normalized = " ".join(sql.split())

    assert "WHEN mp.play_type = 'spf' THEN COALESCE" in normalized
    assert "r.spf_result" in normalized
    assert "WHEN mp.play_type = 'rqspf'" in normalized
    assert "r.rqspf_result" in normalized
    assert "WHEN mp.play_type IN ('zjq', 'total_goals') THEN r.total_goals_result" in normalized
    assert "WHEN mp.play_type IN ('bf', 'score') THEN r.score_result" in normalized
    assert "WHEN mp.play_type IN ('bqc', 'half_full')" in normalized
    assert "r.result_status IN ('final', 'confirmed')" in normalized


def test_backtest_places_only_one_bet_per_match_model_and_play_type() -> None:
    engine = BacktestEngine(
        object(),
        BacktestConfig(signal_strength="all", min_model_prob=0.01),
    )
    rows = [
        _settled_row("3", 0.52, 0.12),
        _settled_row("1", 0.28, 0.08),
        _settled_row("0", 0.20, 0.04),
    ]

    bets = engine._simulate_bets(rows, "2026-07-01", "2026-07-31")

    assert len(bets) == 1
    assert bets[0].option_code == "3"


@pytest.mark.parametrize("confidence", [None, 0.0, 0.8])
def test_backtest_preserves_uncalibrated_confidence(confidence) -> None:
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    row = {**_settled_row("3", 0.52, 0.12), "confidence_score": confidence}

    bets = engine._simulate_bets([row], "2026-07-01", "2026-07-31")

    assert len(bets) == 1
    assert bets[0].confidence == confidence
    assert bets[0].stake == 1.0
    assert bets[0].profit == 2.0
    assert engine.compute_metrics(bets)["total_profit"] == 2.0


def test_backtest_missing_uncalibrated_confidence_stays_unknown() -> None:
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    row = _settled_row("3", 0.52, 0.12)
    del row["confidence_score"]

    bets = engine._simulate_bets([row], "2026-07-01", "2026-07-31")

    assert bets[0].confidence is None


def test_drawdown_is_measured_from_a_real_initial_bankroll() -> None:
    bets = [
        BetRecord(1, "2026-07-01", "elo", "3", 0.5, 0.4, 3.0, 1.0, "3", 2.0, 0.1, 0.8),
        BetRecord(2, "2026-07-02", "elo", "3", 0.5, 0.4, 2.0, 1.0, "0", -1.0, 0.1, 0.8),
        BetRecord(3, "2026-07-03", "elo", "3", 0.5, 0.4, 2.0, 1.0, "0", -1.0, 0.1, 0.8),
        BetRecord(4, "2026-07-04", "elo", "3", 0.5, 0.4, 2.0, 1.0, "0", -1.0, 0.1, 0.8),
    ]

    metrics = BacktestEngine.compute_metrics(bets)

    assert metrics["max_drawdown"] == 3.0
    assert metrics["max_drawdown_pct"] == 2.94
    assert metrics["equity_curve"][0]["bankroll"] == 102.0


def test_backtest_config_records_current_methodology_version() -> None:
    config = BacktestConfig(name="versioned-backtest")

    assert config.to_dict()["methodology_version"] == 4


def test_legacy_config_is_upgraded_when_rerun() -> None:
    config = BacktestConfig.from_dict({"name": "legacy-rerun", "methodology_version": 1})

    assert config.to_dict()["methodology_version"] == 4


def test_backtest_run_is_marked_failed_when_execution_crashes() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (42,)

    with (
        patch.object(BacktestEngine, "run", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        run_backtest_from_config(conn, BacktestConfig(name="failure-test"), store=True)

    executed_sql = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
    assert any("SET status = 'failed'" in sql for sql in executed_sql)


def _research_rows() -> list[ResearchMatch]:
    rows: list[ResearchMatch] = []
    fixtures = ((1, 2), (2, 3), (3, 1))
    first_date = date(2025, 1, 1)
    match_id = 1
    for day_index in range(30):
        business_date = first_date + timedelta(days=day_index)
        for fixture_index, (home_team_id, away_team_id) in enumerate(fixtures):
            kickoff = datetime.combine(business_date, time(20, 0))
            prediction_lead = 30 if day_index == 29 and fixture_index == 1 else 60
            prediction_as_of = kickoff - timedelta(minutes=prediction_lead)
            candidate = CandidateMatch(
                match_id=match_id,
                result_id=match_id + 1000,
                kickoff_at=kickoff,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_goals=(day_index + fixture_index) % 3,
                away_goals=(day_index * 2 + fixture_index) % 2,
                match_status="Settled",
                official_publish_time=(
                    datetime.combine(date(2025, 1, 16), time.min)
                    if day_index == 14 and fixture_index == 0
                    else kickoff + timedelta(hours=3)
                ),
            )
            snapshot_at = prediction_as_of - timedelta(minutes=10)
            odds = {"3": 2.1, "1": 3.2, "0": 3.7}
            snapshot_times = {option: snapshot_at for option in odds}
            if day_index == 27 and fixture_index == 0:
                snapshot_times = {
                    option: prediction_as_of + timedelta(minutes=1) for option in odds
                }
            if day_index == 28 and fixture_index == 0:
                odds = {"3": 2.1, "1": 3.2}
                snapshot_times = {option: snapshot_at for option in odds}
            rows.append(
                ResearchMatch(
                    candidate=candidate,
                    business_date=business_date,
                    prediction_as_of=prediction_as_of,
                    odds_by_option=odds,
                    odds_snapshot_times=snapshot_times,
                    odds_snapshot_ids={option: match_id * 10 + i for i, option in enumerate(odds)},
                    result_status=("pending" if day_index == 9 and fixture_index == 0 else "final"),
                )
            )
            match_id += 1
    return rows


def test_research_splits_keep_business_dates_whole_and_reserve_latest_holdout() -> None:
    rows = _research_rows()

    splits = build_research_time_splits(
        rows,
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    assert len(splits) == 3
    folds, holdout = splits[:-1], splits[-1]
    assert [(fold.test_start, fold.test_end) for fold in folds] == [
        (date(2025, 1, 16), date(2025, 1, 20)),
        (date(2025, 1, 21), date(2025, 1, 25)),
    ]
    assert (holdout.test_start, holdout.test_end) == (date(2025, 1, 26), date(2025, 1, 30))
    assert folds[0].test_end < folds[1].test_start < holdout.test_start


def test_research_reconstruction_refits_each_fold_and_pairs_same_asof_market() -> None:
    rows = _research_rows()

    report = evaluate_research_reconstruction(
        list(reversed(rows)),
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    assert report["evaluation_mode"] == "research_reconstruction"
    assert report["final_holdout"]["evaluation_count"] == 1
    assert report["final_holdout"]["test_start"] == "2025-01-26"
    assert len(report["folds"]) == 2
    assert report["excluded_by_reason"]["incomplete_market_vector"] == 1
    assert report["excluded_by_reason"]["odds_snapshot_after_prediction_as_of"] == 1
    assert report["excluded_by_reason"]["prediction_as_of_does_not_match_config"] == 1

    for fold in [*report["folds"], report["final_holdout"]]:
        assert fold["training_manifest_sha256"]
        assert fold["artifact_identity_sha256"]
        assert fold["train_cutoff"] < f"{fold['test_start']}T00:00:00"
        assert fold["model_market_match_ids"] == fold["model_match_ids"]
        assert fold["model_match_ids"] == fold["market_match_ids"]
        assert fold["sample_count"] > 0
        assert set(fold["metrics"]["model"]) >= {"brier_score", "log_loss", "rps"}
        assert set(fold["metrics"]["market_baseline"]) >= {"brier_score", "log_loss", "rps"}

    assert report["final_holdout"]["test_start"] == "2025-01-26"
    assert report["folds"][-1]["test_end"] < report["final_holdout"]["test_start"]
    assert report["folds"][0]["training_excluded_by_reason"]["label_published_after_cutoff"] == 1
    assert report["folds"][0]["training_excluded_by_reason"]["official_result_not_final"] == 1


def test_research_report_exposes_ambiguous_team_identity() -> None:
    rows = _research_rows()
    target = next(
        row
        for row in rows
        if row.business_date == date(2025, 1, 30) and row.candidate.match_id == 88
    )
    ambiguous = replace(
        target,
        candidate=replace(target.candidate, home_team_id=None),
        team_identity={
            "home": {
                "team_name": "同名球队",
                "selected_team_id": None,
                "name_match_count": 2,
                "candidate_team_ids": [1, 7],
            },
            "away": {
                "team_name": "对手",
                "selected_team_id": 2,
                "name_match_count": 1,
                "candidate_team_ids": [2],
            },
        },
    )
    rows[rows.index(target)] = ambiguous

    report = evaluate_research_reconstruction(
        rows,
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    excluded = next(row for row in report["final_holdout"]["excluded"] if row["match_id"] == 88)
    assert excluded["reason"] == "team_identity_ambiguous"
    assert excluded["team_identity"]["home"]["candidate_team_ids"] == [1, 7]
    audit = next(item for item in report["team_identity_audit"] if item["match_id"] == 88)
    assert audit["home"]["team_name"] == "同名球队"
    assert audit["home"]["selected_team_id"] is None
