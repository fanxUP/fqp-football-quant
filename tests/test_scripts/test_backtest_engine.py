import math
import random
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BetRecord,
    ResearchEvaluationConfig,
    ResearchMatch,
    _research_fixed_window_brier_bound,
    _research_paired_metric_comparison,
    _research_source_snapshot,
    build_research_time_splits,
    compare_prediction_replay_reports,
    evaluate_research_reconstruction,
    load_research_matches,
    run_backtest_from_config,
)
from scripts.training_manifest import CandidateMatch, ResultLabelObservation


@pytest.mark.parametrize(
    "field,value",
    [
        (field, value)
        for field in ("step_days", "train_window_days", "test_window_days")
        for value in (0, -1, 0.5, True, "30", float("inf"), 36501)
    ]
    + [
        ("walk_forward", "false"),
        ("walk_forward", 1),
        ("time_start", "2026-02-30"),
        ("time_end", "20260101"),
        ("stake_per_bet", 0),
        ("stake_per_bet", -1),
        ("stake_per_bet", True),
        ("stake_per_bet", float("nan")),
        ("min_model_prob", 1.1),
        ("confidence_min", -0.1),
        ("odds_min", 1),
        ("ev_min", float("inf")),
        ("signal_strength", "typo"),
        ("model_names", "maher"),
        ("model_ids", [True]),
        ("league_ids", [1]),
        ("risk_levels", ["low"]),
    ],
)
def test_invalid_backtest_configuration_is_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        BacktestConfig(**{field: value})


@pytest.mark.parametrize(
    "fields",
    [
        {"time_start": "2026-02-01", "time_end": "2026-01-01"},
        {"odds_min": 3, "odds_max": 2},
        {"ev_min": 1, "ev_max": 0},
    ],
)
def test_backtest_rejects_reversed_ranges(fields):
    with pytest.raises(ValueError):
        BacktestConfig(**fields)


def test_mutated_configuration_is_rejected_before_creating_a_run():
    cfg = BacktestConfig()
    cfg.step_days = 0
    conn = MagicMock()
    with pytest.raises(ValueError, match="step_days"):
        run_backtest_from_config(conn, cfg)
    conn.cursor.assert_not_called()
    conn.commit.assert_not_called()


def test_backtest_window_work_is_bounded_before_allocating():
    engine = BacktestEngine(object(), BacktestConfig(train_window_days=1, step_days=1))
    with pytest.raises(ValueError, match="窗口"):
        engine._build_windows([date(2020, 1, 1), date(2026, 1, 1)])


def test_backtest_valid_config_keeps_zero_thresholds_and_default_windows():
    cfg = BacktestConfig(
        confidence_min=0,
        min_model_prob=0,
        ev_min=0,
        step_days=1,
        train_window_days=1,
        test_window_days=1,
    )
    windows = BacktestEngine(object(), cfg)._build_windows([date(2026, 1, 1), date(2026, 1, 5)])
    assert len(windows) == 3
    assert [w["test_start"] for w in windows] == [
        "2026-01-03",
        "2026-01-04",
        "2026-01-05",
    ]


def test_model_filter_without_explicit_dates_is_valid():
    assert BacktestConfig(model_names=["maher_poisson"], play_types=["spf"]).time_start is None


def test_backtest_name_respects_existing_database_column_limit():
    assert len(BacktestConfig(name="名" * 255).name) == 255
    with pytest.raises(ValueError, match="name"):
        BacktestConfig(name="名" * 256)


def test_explicit_excessive_window_range_is_rejected_before_run_creation():
    with pytest.raises(ValueError, match="窗口"):
        BacktestConfig(
            time_start="2020-01-01",
            time_end="2026-01-01",
            train_window_days=1,
            step_days=1,
        )


def test_window_dates_near_year_9999_do_not_overflow():
    cfg = BacktestConfig(train_window_days=1, test_window_days=90, step_days=36500)
    windows = BacktestEngine(object(), cfg)._build_windows([date(9999, 12, 28), date.max])
    assert len(windows) == 1
    assert windows[0]["test_end"] == "9999-12-31"


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

    assert "WHEN mp.play_type = 'spf' THEN spf.actual_result" in normalized
    assert "r.spf_result" in normalized
    assert "LEFT JOIN settled_spf_results" in normalized
    assert "r.full_home_goals >= 0" in normalized
    assert "r.full_away_goals >= 0" in normalized
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


@pytest.mark.parametrize("bad", [None, -0.1, 1.1, float("nan"), float("inf"), "bad", True])
def test_backtest_skips_unusable_model_probability_without_blocking_other_matches(bad):
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    good = _settled_row("3", 0.7, 0.1)
    invalid = {**good, "match_id": 102, "model_probability": bad}
    bets = engine._simulate_bets([invalid, good], "2026-07-01", "2026-07-31")
    assert [bet.match_id for bet in bets] == [101]


@pytest.mark.parametrize("bad", [None, -0.1, 1.1, float("nan"), float("inf"), "bad", True])
def test_backtest_missing_market_keeps_profit_and_quality_without_invented_edge(bad):
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    good = _settled_row("3", 0.7, 0.1)
    missing = {**good, "match_id": 102, "market_probability": bad}
    bets = engine._simulate_bets([missing, good], "2026-07-01", "2026-07-31")
    assert len(bets) == 2 and bets[0].market_prob is None
    result = engine.compute_metrics(bets)
    assert result["total_profit"] == 4 and result["brier_score"] == 0.09
    assert result["clv"] is result["probability_edge"] is None


@pytest.mark.parametrize(
    "field,bad",
    [("sp_value", value) for value in (None, 0, 1, -1, float("nan"), float("inf"))]
    + [("ev", value) for value in (None, float("nan"), float("inf"), "bad")],
)
def test_backtest_skips_unusable_odds_or_ev(field, bad):
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    row = {**_settled_row("3", 0.7, 0.1), field: bad}
    assert engine._simulate_bets([row], "2026-07-01", "2026-07-31") == []


def test_backtest_preserves_zero_market_probability_and_unknown_confidence():
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all"))
    row = {
        **_settled_row("3", 1.0, 0.0),
        "market_probability": 0.0,
        "confidence_score": float("nan"),
    }
    bets = engine._simulate_bets([row], "2026-07-01", "2026-07-31")
    assert len(bets) == 1 and bets[0].market_prob == 0
    assert bets[0].confidence is None
    assert engine.compute_metrics(bets)["probability_edge"] == 1.0


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

    assert config.to_dict()["methodology_version"] == 5


def test_legacy_config_is_upgraded_when_rerun() -> None:
    config = BacktestConfig.from_dict({"name": "legacy-rerun", "methodology_version": 1})

    assert config.to_dict()["methodology_version"] == 5


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
    conn.rollback.assert_called_once()


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
                label_observations=(
                    ResultLabelObservation(
                        revision_id=match_id + 5000,
                        result_id=match_id + 1000,
                        fact_status="value",
                        home_goals=(day_index + fixture_index) % 3,
                        away_goals=(day_index * 2 + fixture_index) % 2,
                        published_at=(
                            datetime.combine(date(2025, 1, 16), time.min)
                            if day_index == 14 and fixture_index == 0
                            else kickoff + timedelta(hours=3)
                        )
                        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                        .astimezone(UTC),
                        first_acquired_at=(
                            (
                                datetime.combine(date(2025, 1, 16), time.min)
                                if day_index == 14 and fixture_index == 0
                                else kickoff + timedelta(hours=3)
                            )
                            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                            .astimezone(UTC)
                            + timedelta(minutes=5)
                        ),
                        available_at=(
                            (
                                datetime.combine(date(2025, 1, 16), time.min)
                                if day_index == 14 and fixture_index == 0
                                else kickoff + timedelta(hours=3)
                            )
                            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                            .astimezone(UTC)
                            + timedelta(minutes=10)
                        ),
                    ),
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
                    competition_season_id=20252026,
                    result_status=("pending" if day_index == 9 and fixture_index == 0 else "final"),
                )
            )
            match_id += 1
    return rows


def test_research_paired_metric_comparison_is_date_blocked_and_reproducible() -> None:
    rows = []
    deltas = tuple(-0.1 - (index % 3) / 100 for index in range(30))
    for index, delta in enumerate(deltas):
        model_brier = 0.2 + index / 100
        rows.append(
            {
                "match_id": index + 1,
                "business_date": (date(2025, 1, 1) + timedelta(days=index)).isoformat(),
                "metrics": {
                    "model": {
                        "brier_score": model_brier,
                        "log_loss": 0.8 + index / 100,
                        "rps": 0.3 + index / 100,
                    },
                    "market_baseline": {
                        "brier_score": model_brier - delta,
                        "log_loss": 0.9 + index / 100,
                        "rps": 0.4 + index / 100,
                    },
                },
            }
        )

    comparison = _research_paired_metric_comparison(rows)
    reversed_comparison = _research_paired_metric_comparison(list(reversed(rows)))

    assert comparison == reversed_comparison
    assert comparison["status"] == "descriptive_only"
    assert comparison["sample_count"] == 30
    assert comparison["business_date_cluster_count"] == 30
    assert comparison["decision_eligible"] is False
    assert comparison["promotion_eligible"] is False
    assert comparison["serial_dependence_accounted_for"] is False
    assert comparison["method"] == "paired_mean_by_business_date/v1"
    assert comparison["interval_status"] == "not_computed_serial_dependence_not_modeled"
    assert comparison["serial_dependence_accounted_for"] is False
    assert "bootstrap_seed_sha256" not in comparison
    brier = comparison["metrics"]["brier_score"]
    assert brier["mean_delta"] == pytest.approx(sum(deltas) / len(deltas))
    assert "descriptive_bootstrap_lower" not in brier
    assert "descriptive_bootstrap_upper" not in brier


def test_research_paired_metric_comparison_never_promotes_from_date_count() -> None:
    rows = []
    for index, business_date in enumerate(("2025-01-01", "2025-01-02", "2025-01-03")):
        rows.append(
            {
                "match_id": index + 1,
                "business_date": business_date,
                "metrics": {
                    "model": {"brier_score": 0.1, "log_loss": 0.2, "rps": 0.3},
                    "market_baseline": {
                        "brier_score": 0.2,
                        "log_loss": 0.3,
                        "rps": 0.4,
                    },
                },
            }
        )

    comparison = _research_paired_metric_comparison(rows)

    assert comparison["status"] == "descriptive_only"
    assert comparison["decision_eligible"] is False
    assert comparison["promotion_eligible"] is False
    assert comparison["business_date_cluster_count"] == 3
    assert comparison["interval_status"] == "not_computed_serial_dependence_not_modeled"
    assert "descriptive_bootstrap_lower" not in comparison["metrics"]["brier_score"]


def test_research_paired_metric_comparison_does_not_infer_interval_from_one_date() -> None:
    row = {
        "match_id": 1,
        "business_date": "2025-01-01",
        "metrics": {
            "model": {"brier_score": 0.1, "log_loss": 0.2, "rps": 0.3},
            "market_baseline": {"brier_score": 0.2, "log_loss": 0.3, "rps": 0.4},
        },
    }

    comparison = _research_paired_metric_comparison([row])

    assert comparison["status"] == "insufficient_date_clusters"
    assert comparison["sample_count"] == 1
    assert comparison["business_date_cluster_count"] == 1
    assert comparison["promotion_eligible"] is False
    assert comparison["metrics"]["brier_score"]["mean_delta"] == pytest.approx(-0.1)
    assert comparison["interval_status"] == "not_computed_serial_dependence_not_modeled"
    assert "descriptive_bootstrap_lower" not in comparison["metrics"]["brier_score"]
    assert "descriptive_bootstrap_upper" not in comparison["metrics"]["brier_score"]


def test_research_paired_metric_comparison_requires_a_predeclared_fixed_window_for_bound():
    rows = []
    for index in range(20):
        rows.append(
            {
                "match_id": index + 1,
                "business_date": (date(2025, 1, 1) + timedelta(days=index // 2)).isoformat(),
                "metrics": {
                    "model": {"brier_score": 0.4, "log_loss": 0.2, "rps": 0.3},
                    "market_baseline": {
                        "brier_score": 0.5,
                        "log_loss": 0.3,
                        "rps": 0.4,
                    },
                },
            }
        )

    exploratory = _research_paired_metric_comparison(rows)
    fixed_window = _research_paired_metric_comparison(rows, predeclared_window=True)

    assert exploratory["fixed_horizon_brier_bound"]["status"] == (
        "not_computed_window_not_predeclared"
    )
    bound = fixed_window["fixed_horizon_brier_bound"]
    assert bound["status"] == "computed_fixed_horizon"
    assert bound["method"] == "date_cluster_azuma_hoeffding/v1"
    assert bound["sample_count"] == 20
    assert bound["date_cluster_count"] == 10
    assert bound["effective_date_cluster_count"] == pytest.approx(10)
    assert bound["mean_delta"] == pytest.approx(-0.1)
    expected_radius = 4 * math.sqrt(math.log(2 / 0.05) / (2 * 10))
    assert bound["radius"] == pytest.approx(expected_radius)
    assert bound["lower"] == pytest.approx(-0.1 - expected_radius)
    assert bound["upper"] == pytest.approx(-0.1 + expected_radius)
    assert bound["decision_eligible"] is False
    assert bound["promotion_eligible"] is False


def test_fixed_window_brier_bound_targets_match_weighted_daily_conditional_mean():
    rows = [
        (date(2025, 1, 1), 2.0),
        (date(2025, 1, 2), -1.0),
        (date(2025, 1, 2), -1.0),
        (date(2025, 1, 2), -1.0),
    ]

    bound = _research_fixed_window_brier_bound(rows)

    assert bound["sample_count"] == 4
    assert bound["date_cluster_count"] == 2
    assert bound["mean_delta"] == pytest.approx(-0.25)
    assert bound["target"] == (
        "match_weighted_mean_date_conditional_expected_brier_delta_in_fixed_window"
    )


def test_date_cluster_azuma_hoeffding_bound_covers_correlated_synthetic_sequence():
    rng = random.Random(20261111)
    n = 100
    rho = 0.6
    covered = 0
    repetitions = 500

    for _ in range(repetitions):
        rows = []
        conditional_means = []
        previous = None
        for index in range(n):
            if previous is None:
                state = 1 if rng.random() < 0.5 else -1
                conditional_mean = 0.0
            else:
                conditional_mean = rho * previous
                state = previous if rng.random() < 0.8 else -previous
            rows.append((date(2025, 1, 1) + timedelta(days=index), 2 * state))
            conditional_means.append(2 * conditional_mean)
            previous = state

        bound = _research_fixed_window_brier_bound(rows, alpha=0.05)
        target = math.fsum(conditional_means) / n
        covered += bound["lower"] <= target <= bound["upper"]

    assert covered / repetitions >= 0.95


def test_research_paired_metric_comparison_reports_empty_input_without_interval() -> None:
    comparison = _research_paired_metric_comparison([])

    assert comparison["status"] == "no_paired_observations"
    assert comparison["sample_count"] == 0
    assert comparison["business_date_cluster_count"] == 0
    assert comparison["decision_eligible"] is False
    assert comparison["promotion_eligible"] is False
    assert comparison["metrics"]["brier_score"]["mean_delta"] is None
    assert comparison["interval_status"] == "not_computed_serial_dependence_not_modeled"
    assert "descriptive_bootstrap_lower" not in comparison["metrics"]["brier_score"]
    assert "descriptive_bootstrap_upper" not in comparison["metrics"]["brier_score"]


def test_research_paired_metric_comparison_rejects_duplicate_match_ids() -> None:
    row = {
        "match_id": 1,
        "business_date": "2025-01-01",
        "metrics": {
            "model": {"brier_score": 0.1, "log_loss": 0.2, "rps": 0.3},
            "market_baseline": {"brier_score": 0.2, "log_loss": 0.3, "rps": 0.4},
        },
    }

    with pytest.raises(ValueError, match="unique match IDs"):
        _research_paired_metric_comparison([row, row])


def test_research_paired_metric_comparison_requires_explicit_business_date() -> None:
    row = {
        "match_id": 1,
        "business_date": datetime(2025, 1, 1, tzinfo=UTC),
        "metrics": {
            "model": {"brier_score": 0.1, "log_loss": 0.2, "rps": 0.3},
            "market_baseline": {"brier_score": 0.2, "log_loss": 0.3, "rps": 0.4},
        },
    }

    with pytest.raises(ValueError, match="ISO business date"):
        _research_paired_metric_comparison([row])


def _replay_report(run_id: str, model_version_id: int, rows: list[dict]) -> dict:
    return {
        "schema_version": "fqp.model-time-split-evaluation/v1",
        "evaluation_mode": "prediction_replay",
        "prediction_run_id": run_id,
        "prediction_run_manifest_sha256": f"{model_version_id:064x}",
        "model_manifest_sha256": f"{model_version_id + 1:064x}",
        "input_manifest_sha256": f"{model_version_id + 2:064x}",
        "replay_observed_at": "2026-01-02T00:00:00+00:00",
        "official_prediction_writes": 0,
        "predictions": [
            {
                "match_id": row["match_id"],
                "model_version_id": model_version_id,
                "model_name": row.get(
                    "model_name",
                    "dynamic_team_poisson_shadow" if model_version_id == 501 else "formal_model",
                ),
                "model_is_active": row.get("model_is_active", model_version_id != 501),
                "competition_season_id": row.get("competition_season_id", 20262027),
                "play_type": "spf",
                "business_date": row.get("business_date", "2026-01-01"),
                "predict_time": row.get("predict_time", "2026-01-01T18:00:00"),
                "result_id": row.get("result_id", 100 + row["match_id"]),
                "actual_result": row.get("actual_result", "3"),
                "output_sha256": f"{row['match_id']:064x}",
                "artifact_identity": {
                    "model_name": "dynamic_team_poisson_shadow"
                    if model_version_id == 501
                    else "formal_model",
                    "identity_sha256": f"{model_version_id + 3:064x}",
                    "provenance_status": "complete",
                },
                "odds_snapshot_ids": row.get("odds_snapshot_ids", {"3": 11, "1": 12, "0": 13}),
                "odds_snapshot_times": row.get(
                    "odds_snapshot_times",
                    {option: "2026-01-01T17:50:00" for option in ("3", "1", "0")},
                ),
                "model_probabilities": {"3": 0.5, "1": 0.3, "0": 0.2},
                "market_probabilities": {"3": 0.4, "1": 0.35, "0": 0.25},
                "metrics": {
                    "model": {"brier_score": 0.2, "log_loss": 0.8, "rps": 0.1},
                    "market_baseline": {
                        "brier_score": 0.3,
                        "log_loss": 0.9,
                        "rps": 0.2,
                    },
                },
            }
            for row in rows
        ],
    }


def test_replay_pairs_only_matching_time_result_and_market():
    challenger = _replay_report(
        "candidate-run",
        501,
        [
            {"match_id": 1},
            {"match_id": 2},
            {"match_id": 3},
            {"match_id": 4},
        ],
    )
    incumbent = _replay_report(
        "incumbent-run",
        10,
        [
            {"match_id": 1},
            {"match_id": 2, "predict_time": "2026-01-01T18:01:00"},
            {"match_id": 3, "odds_snapshot_ids": {"3": 21, "1": 22, "0": 23}},
            {"match_id": 4, "result_id": 999},
        ],
    )

    report = compare_prediction_replay_reports(
        challenger,
        incumbent,
        incumbent_model_version_id=10,
    )

    assert report["evaluation_mode"] == "paired_prediction_replay"
    assert report["paired_match_ids"] == [1]
    assert report["sample_count"] == 1
    assert report["official_prediction_writes"] == 0
    assert report["decision_eligible"] is False
    assert report["promotion_eligible"] is False
    assert (
        report["metrics"]["paired_challenger_incumbent"]["metrics"]["brier_score"]["mean_delta"]
        == 0.0
    )
    assert {row["reason"] for row in report["excluded"]} == {
        "prediction_as_of_mismatch",
        "market_snapshot_mismatch",
        "result_identity_mismatch",
    }


def test_replay_pair_requires_model_id_for_multi_model_incumbent():
    challenger = _replay_report("candidate-run", 501, [{"match_id": 1}])
    incumbent = _replay_report("incumbent-run", 10, [{"match_id": 1}])
    incumbent["predictions"].append({**incumbent["predictions"][0], "model_version_id": 11})

    with pytest.raises(ValueError, match="incumbent_model_version_id"):
        compare_prediction_replay_reports(challenger, incumbent)


def test_prediction_replay_pair_rejects_duplicate_match_rows() -> None:
    challenger = _replay_report("candidate-run", 501, [{"match_id": 1}, {"match_id": 1}])
    incumbent = _replay_report("incumbent-run", 10, [{"match_id": 1}])

    with pytest.raises(ValueError, match="duplicate match IDs"):
        compare_prediction_replay_reports(
            challenger,
            incumbent,
            incumbent_model_version_id=10,
        )


def test_prediction_replay_pair_can_require_active_incumbent_attestation() -> None:
    challenger = _replay_report("candidate-run", 501, [{"match_id": 1}])
    incumbent = _replay_report("incumbent-run", 10, [{"match_id": 1, "model_is_active": False}])

    with pytest.raises(ValueError, match="does not attest an active model"):
        compare_prediction_replay_reports(
            challenger,
            incumbent,
            incumbent_model_version_id=10,
            require_active_incumbent=True,
        )


def test_prediction_replay_pair_excludes_missing_or_cross_season_identity() -> None:
    challenger = _replay_report("candidate-run", 501, [{"match_id": 1}, {"match_id": 2}])
    incumbent = _replay_report(
        "incumbent-run",
        10,
        [
            {"match_id": 1, "competition_season_id": None},
            {"match_id": 2, "competition_season_id": 20252026},
        ],
    )

    report = compare_prediction_replay_reports(
        challenger,
        incumbent,
        incumbent_model_version_id=10,
    )

    assert report["sample_count"] == 0
    assert {item["reason"] for item in report["excluded"]} == {
        "season_identity_missing",
        "competition_season_mismatch",
    }


def test_prediction_replay_pair_requires_timestamped_source_attestation() -> None:
    challenger = _replay_report("candidate-run", 501, [{"match_id": 1}])
    incumbent = _replay_report("incumbent-run", 10, [{"match_id": 1}])
    incumbent.pop("replay_observed_at")

    with pytest.raises(ValueError, match="replay_observed_at"):
        compare_prediction_replay_reports(
            challenger,
            incumbent,
            incumbent_model_version_id=10,
            require_active_incumbent=True,
        )


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
    assert (holdout.test_start, holdout.test_end) == (
        date(2025, 1, 26),
        date(2025, 1, 30),
    )
    assert holdout.final_holdout is False
    assert folds[0].test_end < folds[1].test_start < holdout.test_start


def test_predeclared_absolute_final_window_does_not_move_with_later_results() -> None:
    rows = _research_rows()
    config = ResearchEvaluationConfig(
        fold_count=2,
        test_window_days=5,
        holdout_days=5,
        predeclared_final_window_start=date(2025, 1, 26),
        predeclared_final_window_end=date(2025, 1, 30),
    )

    expected = build_research_time_splits(rows, config)
    later_result = SimpleNamespace(business_date=date(2025, 2, 5), result_status="final")
    actual = build_research_time_splits([*rows, later_result], config)

    assert actual == expected
    assert actual[-1].final_holdout is True
    assert (actual[-1].test_start, actual[-1].test_end) == (
        date(2025, 1, 26),
        date(2025, 1, 30),
    )


def test_predeclared_final_window_requires_valid_absolute_boundaries() -> None:
    rows = _research_rows()

    with pytest.raises(ValueError, match="both start and end dates"):
        build_research_time_splits(
            rows,
            ResearchEvaluationConfig(
                fold_count=2,
                test_window_days=5,
                holdout_days=5,
                predeclared_final_window_start=date(2025, 1, 26),
            ),
        )

    with pytest.raises(ValueError, match="length must equal holdout_days"):
        build_research_time_splits(
            rows,
            ResearchEvaluationConfig(
                fold_count=2,
                test_window_days=5,
                holdout_days=5,
                predeclared_final_window_start=date(2025, 1, 25),
                predeclared_final_window_end=date(2025, 1, 30),
            ),
        )


def test_predeclared_final_window_rejects_unresolved_results() -> None:
    rows = _research_rows()
    config = ResearchEvaluationConfig(
        fold_count=2,
        test_window_days=5,
        holdout_days=5,
        predeclared_final_window_start=date(2025, 1, 26),
        predeclared_final_window_end=date(2025, 1, 30),
    )

    with pytest.raises(ValueError, match="contains unresolved results"):
        build_research_time_splits(
            [
                *rows,
                SimpleNamespace(business_date=date(2025, 1, 28), result_status="pending"),
            ],
            config,
        )


@pytest.mark.parametrize(
    "missing_field",
    ("home_goals", "result_id", "label_observations"),
)
def test_predeclared_final_window_rejects_terminal_status_without_complete_result_evidence(
    missing_field: str,
) -> None:
    rows = _research_rows()
    config = ResearchEvaluationConfig(
        fold_count=2,
        test_window_days=5,
        holdout_days=5,
        predeclared_final_window_start=date(2025, 1, 26),
        predeclared_final_window_end=date(2025, 1, 30),
    )
    target_index = 25 * 3
    target = rows[target_index]
    if missing_field == "label_observations":
        candidate = replace(target.candidate, label_observations=())
    else:
        candidate = replace(target.candidate, **{missing_field: None})
    rows[target_index] = replace(target, candidate=candidate, result_status="confirmed")

    with pytest.raises(ValueError, match="contains unresolved results"):
        build_research_time_splits(rows, config)


def test_predeclared_final_window_accepts_database_json_receipt_mappings() -> None:
    rows = _research_rows()
    config = ResearchEvaluationConfig(
        fold_count=2,
        test_window_days=5,
        holdout_days=5,
        predeclared_final_window_start=date(2025, 1, 26),
        predeclared_final_window_end=date(2025, 1, 30),
    )
    target_index = 25 * 3
    target = rows[target_index]
    observation = target.candidate.label_observations[0]
    rows[target_index] = replace(
        target,
        candidate=replace(
            target.candidate,
            label_observations=(
                {
                    "revision_id": observation.revision_id,
                    "result_id": observation.result_id,
                    "fact_status": observation.fact_status,
                    "home_goals": observation.home_goals,
                    "away_goals": observation.away_goals,
                    "published_at": observation.published_at.isoformat(),
                    "first_acquired_at": observation.first_acquired_at.isoformat(),
                    "available_at": observation.available_at.isoformat(),
                },
            ),
        ),
        result_status="confirmed",
    )

    report = evaluate_research_reconstruction(rows, config)

    assert report["final_holdout"]["evaluation_count"] == 1
    assert report["final_holdout"]["sample_count"] > 0


def test_database_loader_json_receipts_reach_predeclared_final_window() -> None:
    source_rows = []
    for research_row in _research_rows():
        candidate = research_row.candidate
        observation = candidate.label_observations[0]
        label_observations = [
            {
                "revision_id": observation.revision_id,
                "result_id": observation.result_id,
                "fact_status": observation.fact_status,
                "home_goals": observation.home_goals,
                "away_goals": observation.away_goals,
                "published_at": observation.published_at.isoformat(),
                "first_acquired_at": observation.first_acquired_at.isoformat(),
                "available_at": observation.available_at.isoformat(),
            }
        ]
        for option_index, (option_code, odds) in enumerate((("3", 2.5), ("1", 3.2), ("0", 2.8))):
            source_rows.append(
                {
                    "match_id": candidate.match_id,
                    "business_date": research_row.business_date,
                    "kickoff_time": candidate.kickoff_at,
                    "match_status": candidate.match_status,
                    "home_team_name": f"Team {candidate.home_team_id}",
                    "away_team_name": f"Team {candidate.away_team_id}",
                    "result_id": candidate.result_id,
                    "official_publish_time": candidate.official_publish_time,
                    "home_goals": candidate.home_goals,
                    "away_goals": candidate.away_goals,
                    "result_status": research_row.result_status,
                    "home_team_id": candidate.home_team_id,
                    "home_team_name_match_count": 1,
                    "home_team_candidate_team_ids": [candidate.home_team_id],
                    "away_team_id": candidate.away_team_id,
                    "away_team_name_match_count": 1,
                    "away_team_candidate_team_ids": [candidate.away_team_id],
                    "label_observations": label_observations,
                    "odds_snapshot_id": candidate.match_id * 10 + option_index,
                    "option_code": option_code,
                    "sp_value": odds,
                    "snapshot_time": research_row.candidate.kickoff_at - timedelta(minutes=60),
                }
            )

    season_ids = {row["match_id"]: 20252026 for row in source_rows}
    with (
        patch("scripts.backtest_engine._execute_read_only_snapshot", return_value=source_rows),
        patch(
            "scripts.backtest_engine._load_verified_competition_season_ids",
            return_value=season_ids,
        ),
    ):
        matches = load_research_matches(object(), max_matches=5000)

    assert matches
    assert isinstance(matches[0].candidate.label_observations[0], ResultLabelObservation)
    report = evaluate_research_reconstruction(
        matches,
        ResearchEvaluationConfig(
            fold_count=2,
            test_window_days=5,
            holdout_days=5,
            predeclared_final_window_start=date(2025, 1, 26),
            predeclared_final_window_end=date(2025, 1, 30),
        ),
    )

    assert report["final_holdout"]["evaluation_count"] == 1
    assert report["final_holdout"]["sample_count"] > 0


def test_research_splits_ignore_unsettled_later_dates_for_holdout_boundary() -> None:
    rows = _research_rows()
    config = ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5)
    expected = build_research_time_splits(rows, config)
    last = rows[-1]
    later_unsettled = replace(
        last,
        candidate=replace(
            last.candidate,
            match_id=9999,
            kickoff_at=datetime(2025, 2, 28, 20, 0),
            label_observations=(),
        ),
        business_date=date(2025, 2, 28),
        result_status="pending",
    )

    actual = build_research_time_splits([*rows, later_unsettled], config)

    assert actual == expected


def test_research_reconstruction_refuses_to_pool_verified_seasons() -> None:
    rows = _research_rows()
    rows[0] = replace(rows[0], competition_season_id=20252026)
    rows[1] = replace(rows[1], competition_season_id=20262027)

    report = evaluate_research_reconstruction(
        rows,
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    assert report["status"] == "not_evaluable"
    assert report["season_scope_status"] == "multiple_verified_seasons"
    assert report["not_evaluable_reason"] == (
        "multiple_verified_seasons_require_separate_evaluations"
    )
    assert report["official_prediction_writes"] == 0


def test_research_reconstruction_rejects_missing_season_identity() -> None:
    rows = [replace(row, competition_season_id=None) for row in _research_rows()]

    report = evaluate_research_reconstruction(
        rows,
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    assert report["status"] == "not_evaluable"
    assert report["season_scope_status"] == "season_identity_incomplete"
    assert report["not_evaluable_reason"] == "verified_season_identity_required"
    assert report["official_prediction_writes"] == 0


def test_research_reconstruction_can_select_one_verified_season() -> None:
    rows = _research_rows()
    rows = [
        replace(
            row,
            competition_season_id=(20252026 if row.business_date < date(2025, 1, 6) else 20262027),
        )
        for row in rows
    ]

    report = evaluate_research_reconstruction(
        rows,
        ResearchEvaluationConfig(
            fold_count=2,
            test_window_days=5,
            holdout_days=5,
            competition_season_id=20262027,
        ),
    )

    assert report["competition_season_id"] == 20262027
    assert report["season_scope_status"] == "verified_requested_season"
    assert report["season_scope_excluded_match_count"] > 0
    assert all(
        prediction["competition_season_id"] == 20262027
        for window in [*report["folds"], report["final_holdout"]]
        for prediction in window["predictions"]
    )


def test_research_splits_accept_prevalidated_date_only_labels() -> None:
    labels = [SimpleNamespace(business_date=date(2025, 1, day)) for day in (1, 2, 3)]

    splits = build_research_time_splits(
        labels,
        ResearchEvaluationConfig(fold_count=1, test_window_days=1, holdout_days=1),
    )

    assert [(split.test_start, split.test_end) for split in splits] == [
        (date(2025, 1, 2), date(2025, 1, 2)),
        (date(2025, 1, 3), date(2025, 1, 3)),
    ]


def test_research_source_snapshot_binds_label_revision_and_availability_times() -> None:
    row = _research_rows()[0]
    observation = row.candidate.label_observations[0]
    changed_observation = replace(
        observation,
        available_at=observation.available_at + timedelta(seconds=1),
    )
    changed = replace(
        row,
        candidate=replace(row.candidate, label_observations=(changed_observation,)),
    )

    assert _research_source_snapshot([row]) != _research_source_snapshot([changed])


def test_research_reconstruction_refits_each_fold_and_pairs_same_asof_market() -> None:
    rows = _research_rows()

    report = evaluate_research_reconstruction(
        list(reversed(rows)),
        ResearchEvaluationConfig(
            fold_count=2,
            test_window_days=5,
            holdout_days=5,
            predeclared_final_window_start=date(2025, 1, 26),
            predeclared_final_window_end=date(2025, 1, 30),
        ),
    )

    assert report["evaluation_mode"] == "research_reconstruction"
    assert report["schema_version"] == "fqp.model-time-split-evaluation/v3"
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
        assert set(fold["metrics"]["market_baseline"]) >= {
            "brier_score",
            "log_loss",
            "rps",
        }
        paired = fold["metrics"]["paired_model_market"]
        assert paired["promotion_eligible"] is False
        assert paired["decision_eligible"] is False
        assert paired["sample_count"] == fold["sample_count"]
        assert paired["business_date_cluster_count"] == len(
            {row["business_date"] for row in fold["predictions"]}
        )
        assert set(paired["metrics"]) == {"brier_score", "log_loss", "rps"}
        assert paired["fixed_horizon_brier_bound"]["status"] == (
            "computed_fixed_horizon"
            if fold["final_holdout"]
            else "not_computed_window_not_predeclared"
        )
        assert "ci_lower" not in paired["metrics"]["brier_score"]

    assert report["final_holdout"]["test_start"] == "2025-01-26"
    assert report["final_holdout"]["window_role"] == "predeclared_final_holdout"
    assert report["config"]["predeclared_final_window_start"] == "2025-01-26"
    assert report["config"]["predeclared_final_window_end"] == "2025-01-30"
    assert report["folds"][-1]["test_end"] < report["final_holdout"]["test_start"]
    assert report["folds"][0]["training_excluded_by_reason"]["result_observation_missing"] == 1
    assert report["folds"][0]["training_match_count"] == 44
    assert "official_result_not_final" not in report["folds"][0]["training_excluded_by_reason"]


def test_rolling_latest_diagnostic_never_emits_formal_brier_bound() -> None:
    report = evaluate_research_reconstruction(
        _research_rows(),
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    latest_window = report["final_holdout"]
    paired = latest_window["metrics"]["paired_model_market"]
    assert latest_window["window_role"] == "rolling_latest_diagnostic"
    assert latest_window["final_holdout"] is False
    assert paired["fixed_horizon_brier_bound"]["status"] == ("not_computed_window_not_predeclared")


def test_research_reconstruction_reports_missing_result_history_as_not_evaluable():
    rows = [
        replace(row, candidate=replace(row.candidate, label_observations=()))
        for row in _research_rows()
    ]

    report = evaluate_research_reconstruction(
        rows,
        ResearchEvaluationConfig(fold_count=2, test_window_days=5, holdout_days=5),
    )

    assert report["status"] == "not_evaluable"
    assert report["not_evaluable_reason"] == "no_source_observed_training_labels_before_cutoff"
    assert report["final_holdout"]["evaluation_count"] == 0
    assert report["final_holdout"]["sample_count"] == 0
    assert report["final_holdout"]["metrics"]["model"]["brier_score"] is None
    assert report["folds"][0]["training_excluded_by_reason"]["result_observation_missing"] > 0
    assert report["claims_model_beats_market"] is False


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


@pytest.mark.parametrize(
    "confidence",
    [None, float("nan"), float("inf"), float("-inf"), -0.1, 1.1, 0.49, True],
)
def test_explicit_confidence_min_rejects_unknown_invalid_or_below_threshold(confidence):
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all", confidence_min=0.5))
    row = {**_settled_row("3", 0.52, 0.12), "confidence_score": confidence}
    assert engine._simulate_bets([row], "2026-07-01", "2026-07-31") == []


@pytest.mark.parametrize("confidence", [0.5, 0.8, 1.0])
def test_explicit_confidence_min_includes_valid_boundary(confidence):
    engine = BacktestEngine(object(), BacktestConfig(signal_strength="all", confidence_min=0.5))
    row = {**_settled_row("3", 0.52, 0.12), "confidence_score": confidence}
    bets = engine._simulate_bets([row], "2026-07-01", "2026-07-31")
    assert len(bets) == 1
    assert bets[0].confidence == confidence
