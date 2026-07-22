from datetime import date

from scripts.model_performance import get_model_performance_history


class HistoryCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params: dict[str, int] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params: dict[str, int]) -> None:
        self.query = " ".join(query.split())
        self.params = params

    def fetchall(self):
        return [
            (
                date(2026, 7, 11), "spf", "elo_rating", 0.6, 5,
                42, 8, date(2026, 6, 1), date(2026, 7, 12),
            ),
            (
                date(2026, 7, 12), "spf", "elo_rating", 0.7, 10,
                42, 8, date(2026, 6, 1), date(2026, 7, 12),
            ),
            (
                date(2026, 7, 12), "bf", "maher_poisson", 0.2, 5,
                5, 1, date(2026, 7, 12), date(2026, 7, 12),
            ),
        ]


class HistoryConnection:
    def __init__(self) -> None:
        self.cursor_instance = HistoryCursor()

    def cursor(self) -> HistoryCursor:
        return self.cursor_instance


def test_model_performance_history_returns_rolling_hit_rate_by_play_type() -> None:
    conn = HistoryConnection()

    result = get_model_performance_history(conn, window=20, days=90)

    assert "source_mp.validation_status = 'valid'" in conn.cursor_instance.query
    assert "model_independent" in conn.cursor_instance.query

    assert result == {
        "status": "ok",
        "metric": "rolling_hit_rate",
        "window": 20,
        "days": 90,
        "points": [
            {
                "date": "2026-07-11",
                "play_type": "spf",
                "model_name": "elo_rating",
                "hit_rate": 0.6,
                "sample_size": 5,
            },
            {
                "date": "2026-07-12",
                "play_type": "spf",
                "model_name": "elo_rating",
                "hit_rate": 0.7,
                "sample_size": 10,
            },
            {
                "date": "2026-07-12",
                "play_type": "bf",
                "model_name": "maher_poisson",
                "hit_rate": 0.2,
                "sample_size": 5,
            },
        ],
        "samples": [
            {
                "play_type": "spf",
                "model_name": "elo_rating",
                "total_samples": 42,
                "settled_dates": 8,
                "first_date": "2026-06-01",
                "last_date": "2026-07-12",
            },
            {
                "play_type": "bf",
                "model_name": "maher_poisson",
                "total_samples": 5,
                "settled_dates": 1,
                "first_date": "2026-07-12",
                "last_date": "2026-07-12",
            },
        ],
    }
    assert conn.cursor_instance.params == {"days": 90, "preceding": 19}


def test_model_performance_history_uses_top_pick_and_all_official_result_types() -> None:
    conn = HistoryConnection()

    get_model_performance_history(conn, window=10, days=365)

    query = conn.cursor_instance.query
    assert "ROW_NUMBER() OVER" in query
    assert "source_mp.predict_time < m.kickoff_time" in query
    assert "model_probability DESC" in query
    assert "r.spf_result" in query
    assert "r.rqspf_result" in query
    assert "r.total_goals_result" in query
    assert "r.score_result" in query
    assert "r.half_full_result" in query
    assert "handicap" in query
    assert "UNION ALL" in query
    assert "'all' AS play_type" in query
    assert "ROWS BETWEEN %(preceding)s PRECEDING" in query
    assert "COUNT(*) AS total_samples" in query
    assert "COUNT(DISTINCT business_date) AS settled_dates" in query
