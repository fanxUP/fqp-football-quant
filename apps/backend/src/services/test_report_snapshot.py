from apps.backend.src.services.report_snapshot import build_daily_report_snapshot


def test_daily_report_snapshot_freezes_match_result_prematch_signals_and_evidence() -> None:
    snapshot = build_daily_report_snapshot(
        review={"reviewId": 8, "reviewDate": "2026-08-09", "summary": "已结算"},
        upset_report={"upsetCount": 1},
        match_cards=[
            {
                "matchId": 101,
                "officialCode": "周日001",
                "leagueName": "英超",
                "homeTeamName": "主队",
                "awayTeamName": "客队",
                "kickoffTime": "2026-08-09T18:00:00",
                "result": {"homeGoals": 2, "awayGoals": 1, "status": "confirmed"},
                "modelSignals": [{"modelName": "Poisson", "playType": "spf", "optionCode": "h"}],
                "oddsSignals": [{"playType": "spf", "optionCode": "h", "spValue": 1.8}],
                "evidence": [{"sourceName": "官方来源", "headline": "赛后信息"}],
                "evidenceStatus": "已收录",
            },
            {
                "matchId": 102,
                "officialCode": "周日002",
                "leagueName": "法甲",
                "homeTeamName": "甲队",
                "awayTeamName": "乙队",
                "kickoffTime": "2026-08-09T21:00:00",
                "result": {"homeGoals": 0, "awayGoals": 0, "status": "confirmed"},
                "modelSignals": [],
                "oddsSignals": [],
                "evidence": [],
                "evidenceStatus": "未查到可靠资料",
            },
        ],
    )

    assert snapshot["schemaVersion"] == 1
    assert snapshot["dailyReview"]["reviewId"] == 8
    assert snapshot["upsetReport"] == {"upsetCount": 1}
    assert snapshot["matches"][0]["result"]["homeGoals"] == 2
    assert snapshot["matches"][0]["modelSignals"][0]["modelName"] == "Poisson"
    assert snapshot["matches"][0]["oddsSignals"][0]["spValue"] == 1.8
    assert snapshot["matches"][0]["evidence"][0]["sourceName"] == "官方来源"
    assert snapshot["matches"][1]["evidenceStatus"] == "未查到可靠资料"
