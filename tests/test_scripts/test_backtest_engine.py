from unittest.mock import MagicMock, patch

import pytest

from scripts.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BetRecord,
    run_backtest_from_config,
)


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
