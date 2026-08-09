from apps.backend.src.services.report_snapshot import (
    build_daily_report_snapshot,
    build_periodic_research_metrics,
)


def test_periodic_research_metrics_weights_signal_quality_by_signal_count() -> None:
    metrics = build_periodic_research_metrics([
        {
            "periodKey": "2026-08-08",
            "researchMetrics": {
                "matchCount": 2, "signalCount": 2, "signalMatchCount": 1,
                "evidenceMatchCount": 1, "averageModelProbability": 0.6,
                "averageMarketProbability": 0.5, "averageEdge": 0.1, "averageEv": 0.2,
            },
        },
        {
            "periodKey": "2026-08-09",
            "researchMetrics": {
                "matchCount": 3, "signalCount": 1, "signalMatchCount": 1,
                "evidenceMatchCount": 3, "averageModelProbability": 0.9,
                "averageMarketProbability": 0.8, "averageEdge": 0.1, "averageEv": 0.3,
            },
        },
    ])

    assert metrics == {
        "dailyReportCount": 2,
        "researchMetricDayCount": 2,
        "matchCount": 5,
        "signalCount": 3,
        "signalMatchCount": 2,
        "signalCoverageRate": 0.4,
        "evidenceMatchCount": 4,
        "evidenceCoverageRate": 0.8,
        "averageModelProbability": 0.7,
        "averageMarketProbability": 0.6,
        "averageEdge": 0.1,
        "averageEv": 0.2333,
    }


def test_daily_report_snapshot_freezes_match_result_prematch_signals_and_evidence() -> None:
    snapshot = build_daily_report_snapshot(
        review={
            "reviewId": 8,
            "reviewDate": "2026-08-09",
            "summary": "已结算",
            "actualStake": 200,
            "realPrize": 260,
            "realProfitLoss": 60,
            "realRoi": 0.3,
        },
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
                "modelSignals": [{
                    "modelName": "Poisson", "playType": "spf", "optionCode": "h",
                    "modelProbability": 0.62, "marketProbability": 0.55, "ev": 0.12,
                }],
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

    assert snapshot["schemaVersion"] == 2
    assert snapshot["dailyReview"]["reviewId"] == 8
    assert snapshot["upsetReport"] == {"upsetCount": 1}
    assert snapshot["matches"][0]["result"]["homeGoals"] == 2
    assert snapshot["matches"][0]["modelSignals"][0]["modelName"] == "Poisson"
    assert snapshot["matches"][0]["oddsSignals"][0]["spValue"] == 1.8
    assert snapshot["matches"][0]["evidence"][0]["sourceName"] == "官方来源"
    assert snapshot["matches"][1]["evidenceStatus"] == "未查到可靠资料"
    assert snapshot["researchMetrics"] == {
        "matchCount": 2,
        "signalMatchCount": 1,
        "signalCoverageRate": 0.5,
        "evidenceMatchCount": 1,
        "evidenceCoverageRate": 0.5,
        "signalCount": 1,
        "averageModelProbability": 0.62,
        "averageMarketProbability": 0.55,
        "averageEdge": 0.07,
        "averageEv": 0.12,
        "actualStake": 200.0,
        "realPrize": 260.0,
        "realProfitLoss": 60.0,
        "realRoi": 0.3,
    }
