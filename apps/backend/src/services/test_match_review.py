from __future__ import annotations

from apps.backend.src.services.match_review import build_match_review_cards


class _Cursor:
    def __init__(self) -> None:
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, _params) -> None:
        if "FROM model_predictions" in query:
            self._rows = [(7, "Elo", "spf", "home_win", 0.62, 0.55, 0.12, 0.78, "2026-08-09T10:00:00")]
        elif "FROM official_odds_snapshots" in query:
            self._rows = [(7, "spf", "home_win", "主胜", 1.82, None, "2026-08-09T17:00:00")]
        elif "FROM official_matches" in query:
            self._rows = [(7, "周日001", "英超", "主队", "客队", "2026-08-09T18:00:00", "finished", 2, 1, "主胜", "confirmed", "2026-08-09T20:00:00")]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _Connection:
    def cursor(self):
        return _Cursor()


def test_match_review_card_combines_official_result_pre_match_signals_and_empty_evidence() -> None:
    cards = build_match_review_cards(_Connection(), "2026-08-09")

    assert cards == [{
        "matchId": 7,
        "officialCode": "周日001",
        "leagueName": "英超",
        "homeTeamName": "主队",
        "awayTeamName": "客队",
        "kickoffTime": "2026-08-09T18:00:00",
        "result": {"homeGoals": 2, "awayGoals": 1, "spfResult": "主胜", "status": "confirmed", "publishedAt": "2026-08-09T20:00:00"},
        "modelSignals": [{"modelName": "Elo", "playType": "spf", "optionCode": "home_win", "modelProbability": 0.62, "marketProbability": 0.55, "ev": 0.12, "confidenceScore": 0.78, "predictTime": "2026-08-09T10:00:00"}],
        "oddsSignals": [{"playType": "spf", "optionCode": "home_win", "optionName": "主胜", "spValue": 1.82, "handicap": None, "snapshotTime": "2026-08-09T17:00:00"}],
        "evidence": [],
        "evidenceStatus": "未查到可靠资料",
    }]
