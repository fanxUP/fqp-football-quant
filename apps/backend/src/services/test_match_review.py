from __future__ import annotations

from apps.backend.src.services.match_review import build_match_review_cards


class _Cursor:
    def __init__(self) -> None:
        self._rows: list[tuple] = []
        self.calls: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params) -> None:
        self.calls.append((query, params))
        if "factor_value_json->>'summary'" in query:
            assert "factor_value_json->>'summary' AS summary" in query
        if (
            "FROM model_prediction_latest_rows" in query
            or "FROM canonical_prediction_rows" in query
        ):
            self._rows = [
                (7, "Elo", "spf", "home_win", 0.62, 0.55, 0.12, 0.78, "2026-08-09T10:00:00")
            ]
        elif "FROM official_odds_snapshots" in query:
            self._rows = [(7, "spf", "home_win", "主胜", 1.82, None, "2026-08-09T17:00:00")]
        elif "FROM upset_factor_evidence" in query:
            self._rows = [
                (
                    7,
                    "post_match",
                    "api_football_match_data",
                    "api_fixture:88",
                    None,
                    "2026-08-09T19:00:00",
                    "主队在第80分钟进球",
                    None,
                    "verified",
                )
            ]
        elif "FROM official_matches" in query:
            self._rows = [
                (
                    7,
                    "周日001",
                    "英超",
                    "主队",
                    "客队",
                    "2026-08-09T18:00:00",
                    "finished",
                    2,
                    1,
                    "3",
                    "1",
                    "3",
                    "2:1",
                    "3-3",
                    "confirmed",
                    "2026-08-09T20:00:00",
                )
            ]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _Connection:
    def cursor(self):
        return _Cursor()


class _RecordingConnection(_Connection):
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()

    def cursor(self):
        return self.cursor_instance


def test_match_review_card_combines_official_result_pre_match_signals_and_empty_evidence() -> None:
    cards = build_match_review_cards(_Connection(), "2026-08-09")

    assert cards == [
        {
            "matchId": 7,
            "officialCode": "周日001",
            "leagueName": "英超",
            "homeTeamName": "主队",
            "awayTeamName": "客队",
            "kickoffTime": "2026-08-09T18:00:00",
            "result": {
                "homeGoals": 2,
                "awayGoals": 1,
                "spfResult": "3",
                "rqspfResult": "1",
                "totalGoalsResult": "3",
                "scoreResult": "2:1",
                "halfFullResult": "3-3",
                "status": "confirmed",
                "publishedAt": "2026-08-09T20:00:00",
            },
            "modelSignals": [
                {
                    "modelName": "Elo",
                    "playType": "spf",
                    "optionCode": "home_win",
                    "modelProbability": 0.62,
                    "marketProbability": 0.55,
                    "ev": 0.12,
                    "confidenceScore": 0.78,
                    "predictTime": "2026-08-09T10:00:00",
                }
            ],
            "oddsSignals": [
                {
                    "playType": "spf",
                    "optionCode": "home_win",
                    "optionName": "主胜",
                    "spValue": 1.82,
                    "handicap": None,
                    "snapshotTime": "2026-08-09T17:00:00",
                }
            ],
            "evidence": [
                {
                    "phase": "post_match",
                    "sourceType": "api_football_match_data",
                    "sourceName": "API-Football 比赛资料",
                    "sourceReference": "api_fixture:88",
                    "sourceUrl": None,
                    "publishedAt": None,
                    "capturedAt": "2026-08-09T19:00:00",
                    "headline": "主队在第80分钟进球",
                    "summary": None,
                    "reliability": "verified",
                }
            ],
            "evidenceStatus": "已收录",
        }
    ]


def test_match_review_prediction_read_scopes_canonical_selection_to_review_matches() -> None:
    conn = _RecordingConnection()

    build_match_review_cards(conn, "2026-08-09")

    query, params = next(
        (query, params)
        for query, params in conn.cursor_instance.calls
        if "model_prediction_latest_rows" in query or "canonical_prediction_rows" in query
    )
    assert "model_prediction_latest_rows" not in query
    assert "review_match_scope AS MATERIALIZED" in query
    assert "g.match_id = ANY(ARRAY(SELECT match_id FROM review_match_scope))" in query
    assert "p.match_id = scoped.match_id" in query
    assert "validation_status = 'valid'" in query
    assert "predict_time <" in query
    assert params == {"match_ids": [7]}
