from __future__ import annotations

from scripts.jobs.backfill_report_snapshots import (
    build_daily_backfill_snapshot,
    build_periodic_backfill_snapshot,
)


def _daily_card() -> dict:
    return {
        "matchId": 7,
        "leagueName": "英超",
        "kickoffTime": "2026-08-09T18:00:00",
        "result": {"spfResult": "3", "status": "confirmed"},
        "modelSignals": [
            {"modelName": "Elo", "playType": "spf", "optionCode": "3", "modelProbability": 0.6, "marketProbability": 0.5},
            {"modelName": "Elo", "playType": "spf", "optionCode": "1", "modelProbability": 0.25, "marketProbability": 0.28},
            {"modelName": "Elo", "playType": "spf", "optionCode": "0", "modelProbability": 0.15, "marketProbability": 0.22},
        ],
        "oddsSignals": [
            {"playType": "spf", "optionCode": "3", "spValue": 2.0},
            {"playType": "spf", "optionCode": "1", "spValue": 3.2},
            {"playType": "spf", "optionCode": "0", "spValue": 3.8},
        ],
        "evidence": [],
    }


def test_daily_backfill_builds_v4_snapshot_and_marks_interpretation_for_refresh() -> None:
    upgraded = build_daily_backfill_snapshot(
        "2026-08-09",
        {
            "schemaVersion": 3,
            "dailyReview": {"reviewDate": "2026-08-09", "actualStake": 100},
            "upsetReport": {"metrics": {"upsets": {"count": 1}}},
        },
        [_daily_card()],
    )

    assert upgraded["schemaVersion"] == 4
    assert upgraded["dailyReview"]["actualStake"] == 100
    assert upgraded["performanceMetrics"]["sampleCount"] == 1
    assert upgraded["backfill"] == {
        "reason": "升级真实赛果评价与证据复盘",
        "supersedesSchemaVersion": 3,
        "interpretationRequiresRefresh": True,
    }


def test_periodic_backfill_merges_only_frozen_daily_v4_snapshots() -> None:
    daily = build_daily_backfill_snapshot(
        "2026-08-09",
        {"schemaVersion": 3, "dailyReview": {}, "upsetReport": {}},
        [_daily_card()],
    )
    upgraded = build_periodic_backfill_snapshot(
        {"schemaVersion": 2, "aggregate": {"total_stake": 100}, "upsetReport": {}},
        [{"periodKey": "2026-08-09", **daily}],
    )

    assert upgraded["schemaVersion"] == 4
    assert upgraded["aggregate"]["total_stake"] == 100
    assert upgraded["performanceMetrics"]["sampleCount"] == 1
    assert upgraded["dailyReportRefs"] == ["2026-08-09"]
