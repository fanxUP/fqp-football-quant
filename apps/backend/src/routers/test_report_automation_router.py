from __future__ import annotations

from apps.backend.src.routers.report_automation import get_report_snapshot_for_source


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, _query: str, _params: tuple[str, str]) -> None:
        return None

    def fetchone(self):
        return (
            {
                "schemaVersion": 4,
                "researchMetrics": {"matchCount": 3},
                "performanceMetrics": {"sampleCount": 9, "hitRate": 0.5556},
                "performanceBreakdowns": {"models": [{"key": "Elo", "sampleCount": 3}]},
                "evidenceSummary": {"newsEvidenceCount": 0},
                "errorAnalysis": {"errorCount": 4, "items": [{"matchId": 99}]},
                "strategySummary": {"status": "review_required"},
                "upsetSummary": {"count": 1},
                "backfill": {"interpretationRequiresRefresh": True},
                "performanceSeries": [{"matchId": 99}],
                "matches": [{"matchId": 99}],
            },
            2,
        )


class _Connection:
    def cursor(self):
        return _Cursor()


def test_snapshot_api_exposes_safe_performance_summary_without_raw_match_series() -> None:
    report = get_report_snapshot_for_source(
        _Connection(), source_type="post_daily", source_ref="2026-08-09"
    )

    assert report is not None
    assert report["performanceMetrics"]["sampleCount"] == 9
    assert report["performanceBreakdowns"]["models"][0]["key"] == "Elo"
    assert report["evidenceSummary"]["newsEvidenceCount"] == 0
    assert report["errorAnalysis"] == {"errorCount": 4, "byType": []}
    assert report["strategySummary"]["status"] == "review_required"
    assert report["upsetSummary"]["count"] == 1
    assert report["snapshotRevision"] == 2
    assert report["interpretationRequiresRefresh"] is True
    assert "performanceSeries" not in report
    assert "matches" not in report
