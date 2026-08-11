from __future__ import annotations

from apps.backend.src.services.report_performance import (
    build_daily_performance,
    build_periodic_performance,
)


def _card(
    *,
    match_id: int,
    actual: str,
    probabilities: tuple[float, float, float],
    market_probabilities: tuple[float, float, float],
    odds: tuple[float, float, float],
    evidence: list[dict] | None = None,
) -> dict:
    options = ("3", "1", "0")
    return {
        "matchId": match_id,
        "leagueName": "英超",
        "kickoffTime": f"2026-08-0{match_id}T18:00:00",
        "result": {"spfResult": actual, "status": "confirmed"},
        "modelSignals": [
            {
                "modelName": "Poisson",
                "playType": "spf",
                "optionCode": option,
                "modelProbability": probability,
                "marketProbability": market,
                "ev": probability * odd - 1,
            }
            for option, probability, market, odd in zip(
                options, probabilities, market_probabilities, odds, strict=True
            )
        ],
        "oddsSignals": [
            {
                "playType": "spf",
                "optionCode": option,
                "spValue": odd,
                "snapshotTime": f"2026-08-0{match_id}T17:55:00",
            }
            for option, odd in zip(options, odds, strict=True)
        ],
        "evidence": evidence or [],
    }


def test_daily_performance_scores_true_outcomes_clv_calibration_and_breakdowns() -> None:
    report = build_daily_performance(
        [
            _card(
                match_id=1,
                actual="3",
                probabilities=(0.60, 0.25, 0.15),
                market_probabilities=(0.50, 0.28, 0.22),
                odds=(2.00, 3.20, 3.80),
                evidence=[
                    {
                        "phase": "pre_match",
                        "sourceType": "official_news",
                        "reliability": "official",
                    },
                    {
                        "phase": "post_match",
                        "sourceType": "api_football_match_data",
                        "reliability": "verified",
                    },
                ],
            ),
            _card(
                match_id=2,
                actual="0",
                probabilities=(0.55, 0.25, 0.20),
                market_probabilities=(0.48, 0.27, 0.25),
                odds=(1.80, 3.40, 4.20),
            ),
        ]
    )

    metrics = report["performanceMetrics"]
    assert metrics["sampleCount"] == 2
    assert metrics["correctCount"] == 1
    assert metrics["hitRate"] == 0.5
    assert metrics["brierScore"] is not None
    assert metrics["logLoss"] is not None
    assert metrics["averageClv"] is not None
    assert metrics["averageClosingEdge"] is not None
    assert metrics["calibrationError"] is not None
    assert metrics["maxLosingStreak"] == 1
    assert metrics["unitStakeProfit"] == 0.0
    assert metrics["unitStakeRoi"] == 0.0

    model = report["performanceBreakdowns"]["models"][0]
    assert model["key"] == "Poisson"
    assert model["sampleCount"] == 2
    assert model["correctCount"] == 1
    assert model["hitRate"] == 0.5
    assert model["unitStakeRoi"] == 0.0

    assert report["evidenceSummary"] == {
        "evidenceCount": 2,
        "coveredMatchCount": 1,
        "preMatchCount": 1,
        "postMatchCount": 1,
        "newsEvidenceCount": 1,
        "officialOrVerifiedCount": 2,
        "missingMatchCount": 1,
    }
    assert report["errorAnalysis"]["errorCount"] == 1
    assert report["errorAnalysis"]["byType"][0]["code"] == "FAVOURITE_DIRECTION_REVERSED"
    assert report["strategySummary"]["status"] == "review_required"


def test_periodic_performance_merges_daily_results_without_re_scoring_business_facts() -> None:
    first = build_daily_performance(
        [
            _card(
                match_id=1,
                actual="3",
                probabilities=(0.60, 0.25, 0.15),
                market_probabilities=(0.50, 0.28, 0.22),
                odds=(2.00, 3.20, 3.80),
            )
        ]
    )
    second = build_daily_performance(
        [
            _card(
                match_id=2,
                actual="0",
                probabilities=(0.55, 0.25, 0.20),
                market_probabilities=(0.48, 0.27, 0.25),
                odds=(1.80, 3.40, 4.20),
            )
        ]
    )

    periodic = build_periodic_performance(
        [
            {"periodKey": "2026-08-01", **first},
            {"periodKey": "2026-08-02", **second},
        ]
    )

    assert periodic["performanceMetrics"]["sampleCount"] == 2
    assert periodic["performanceMetrics"]["correctCount"] == 1
    assert periodic["performanceMetrics"]["hitRate"] == 0.5
    assert periodic["performanceMetrics"]["maxLosingStreak"] == 1
    assert periodic["performanceBreakdowns"]["models"][0]["sampleCount"] == 2
    assert periodic["evidenceSummary"]["missingMatchCount"] == 2
    assert periodic["errorAnalysis"]["errorCount"] == 1
