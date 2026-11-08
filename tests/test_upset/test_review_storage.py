from __future__ import annotations

from datetime import datetime

from scripts.upset.review_storage import _prediction_evidence


class _Cursor:
    def __init__(self) -> None:
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params) -> None:
        self.query = query
        self.params = params

    def fetchone(self):
        return {
            "id": 123,
            "predict_time": datetime(2026, 8, 9, 10),
            "option_code": "3",
            "model_probability": 0.61,
            "market_probability": 0.55,
            "ev": 0.1,
            "validation_status": "valid",
            "model_name": "Maher",
            "version": "v1",
        }


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()

    def cursor(self, *, cursor_factory=None):
        return self.cursor_instance


def test_upset_prediction_evidence_scopes_canonical_read_to_event_match() -> None:
    conn = _Connection()
    event = {
        "id": 45,
        "match_id": 7,
        "primary_play_type": "spf",
        "kickoff_time": datetime(2026, 8, 9, 18),
    }

    evidence = _prediction_evidence(conn, event)

    query = conn.cursor_instance.query
    assert "model_prediction_latest_rows" not in query
    assert "upset_match_scope AS MATERIALIZED" in query
    assert (
        "JOIN (SELECT DISTINCT match_id FROM upset_match_scope) group_scope "
        "ON group_scope.match_id = g.match_id"
    ) in query
    assert "p.match_id = scoped.match_id" in query
    assert "play_type" in query
    assert "validation_status = 'valid'" in query
    assert "model_independent" in query
    assert "predict_time <" in query
    assert conn.cursor_instance.params == {
        "match_id": 7,
        "play_type": "spf",
        "kickoff_time": event["kickoff_time"],
    }
    assert evidence["source_reference"] == "model_prediction:123"
    assert evidence["available_before_kickoff"] is True
