from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from apps.backend.src import db
from scripts.evaluation_metrics import compute_match_metrics, run


def test_match_metrics_separates_market_move_from_model_closing_edge() -> None:
    metrics = compute_match_metrics(
        {"3": 0.60, "1": 0.25, "0": 0.15},
        {"3": 0.50, "1": 0.28, "0": 0.22},
        "3",
        model_name="Elo",
        closing_market_probs={"3": 0.54, "1": 0.26, "0": 0.20},
        closing_odds={"3": 2.0, "1": 3.2, "0": 3.8},
    )

    assert metrics["option_code"] == "3"
    assert metrics["model_probability"] == 0.60
    assert metrics["market_probability"] == 0.50
    assert metrics["closing_market_probability"] == 0.54
    assert metrics["probability_gap"] == 0.06
    # Stored legacy clv_score is explicitly a market-probability move.
    assert metrics["clv_score"] == 0.04
    assert metrics["closing_edge_3"] == 0.06
    assert metrics["official_sp"] == 2.0
    assert metrics["fair_odds"] == 1.6667
    assert metrics["ev"] == 0.2


def test_run_normalizes_official_spf_option_codes_before_clv_join(monkeypatch: Any) -> None:
    class _Cursor:
        query = ""

        def execute(self, query: str) -> None:
            self.query = query

        def fetchall(self) -> list[tuple]:
            return []

    class _Connection:
        cursor_instance = _Cursor()

        def cursor(self) -> _Cursor:
            return self.cursor_instance

    connection = _Connection()

    @contextmanager
    def _get_db():
        yield connection

    monkeypatch.setattr(db, "get_db", _get_db)

    assert run() == {"status": "ok", "evaluated": 0, "note": "no new predictions to evaluate"}
    query = connection.cursor_instance.query
    assert "WHEN odds.option_code = 'h' THEN '3'" in query
    assert "WHEN odds.option_code = 'd' THEN '1'" in query
    assert "WHEN odds.option_code = 'a' THEN '0'" in query
