"""Immutable, backend-built source snapshots for generated reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

_MATCH_CARD_FIELDS = (
    "matchId",
    "officialCode",
    "leagueName",
    "homeTeamName",
    "awayTeamName",
    "kickoffTime",
    "result",
    "modelSignals",
    "oddsSignals",
    "evidence",
    "evidenceStatus",
)


def _number(value: Any) -> float | None:
    """Return a finite report metric value without trusting sparse signal rows."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _average(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def build_daily_research_metrics(
    review: Mapping[str, Any],
    match_cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build compact, factual research metrics from a frozen daily source.

    These metrics describe coverage and historical outcomes only. They never
    create predictions, recommendations, or changes to ticket records.
    """
    signals = [
        signal
        for card in match_cards
        for signal in (card.get("modelSignals") or [])
        if isinstance(signal, Mapping)
    ]
    model_probabilities = [
        value
        for signal in signals
        if (value := _number(signal.get("modelProbability"))) is not None
    ]
    market_probabilities = [
        value
        for signal in signals
        if (value := _number(signal.get("marketProbability"))) is not None
    ]
    edges = [
        model - market
        for signal in signals
        if (model := _number(signal.get("modelProbability"))) is not None
        and (market := _number(signal.get("marketProbability"))) is not None
    ]
    expected_values = [
        value
        for signal in signals
        if (value := _number(signal.get("ev"))) is not None
    ]
    match_count = len(match_cards)
    signal_match_count = sum(bool(card.get("modelSignals")) for card in match_cards)
    evidence_match_count = sum(bool(card.get("evidence")) for card in match_cards)

    return {
        "matchCount": match_count,
        "signalMatchCount": signal_match_count,
        "signalCoverageRate": round(signal_match_count / match_count, 4) if match_count else 0.0,
        "evidenceMatchCount": evidence_match_count,
        "evidenceCoverageRate": round(evidence_match_count / match_count, 4) if match_count else 0.0,
        "signalCount": len(signals),
        "averageModelProbability": _average(model_probabilities),
        "averageMarketProbability": _average(market_probabilities),
        "averageEdge": _average(edges),
        "averageEv": _average(expected_values),
        "actualStake": _number(review.get("actualStake")) or 0.0,
        "realPrize": _number(review.get("realPrize")) or 0.0,
        "realProfitLoss": _number(review.get("realProfitLoss")) or 0.0,
        "realRoi": _number(review.get("realRoi")) or 0.0,
    }


def build_daily_report_snapshot(
    *,
    review: Mapping[str, Any],
    upset_report: Mapping[str, Any],
    match_cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze read-only facts used for a daily post-match report.

    Match cards are assembled on the backend from confirmed official results,
    pre-kickoff predictions, final available official odds, and stored evidence.
    This helper deliberately omits any mutable frontend input.
    """
    matches = [
        {field: deepcopy(card.get(field)) for field in _MATCH_CARD_FIELDS}
        for card in match_cards
    ]
    return {
        "schemaVersion": 2,
        "sourceNotice": (
            "比赛、赛果、赛前模型信号和官方赔率均由后端只读归档；"
            "证据缺失时明确标记为未查到可靠资料。"
        ),
        "dailyReview": deepcopy(dict(review)),
        "researchMetrics": build_daily_research_metrics(review, match_cards),
        "matches": matches,
        "upsetReport": deepcopy(dict(upset_report)),
    }
