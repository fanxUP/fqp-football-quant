"""Immutable, backend-built source snapshots for generated reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from apps.backend.src.services.report_performance import build_daily_performance

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


def _signal_breakdown_row(
    key: str, signals: Sequence[tuple[int, Mapping[str, Any]]]
) -> dict[str, Any]:
    """Return one factual signal group without deriving outcome quality."""
    model_probabilities = [
        value
        for _match_id, signal in signals
        if (value := _number(signal.get("modelProbability"))) is not None
    ]
    market_probabilities = [
        value
        for _match_id, signal in signals
        if (value := _number(signal.get("marketProbability"))) is not None
    ]
    edges = [
        model - market
        for _match_id, signal in signals
        if (model := _number(signal.get("modelProbability"))) is not None
        and (market := _number(signal.get("marketProbability"))) is not None
    ]
    expected_values = [
        value for _match_id, signal in signals if (value := _number(signal.get("ev"))) is not None
    ]
    return {
        "key": key,
        "signalCount": len(signals),
        "matchCount": len({match_id for match_id, _signal in signals}),
        "averageModelProbability": _average(model_probabilities),
        "averageMarketProbability": _average(market_probabilities),
        "averageEdge": _average(edges),
        "averageEv": _average(expected_values),
    }


def _sort_breakdown(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (-row["signalCount"], row["key"]))


def build_daily_research_breakdowns(
    match_cards: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group frozen pre-match signals for descriptive report comparisons.

    These are signal-distribution rows, not model performance scores: all
    outcome quality must continue to come from the dedicated evaluation flow.
    """
    models: defaultdict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    play_types: defaultdict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    leagues: defaultdict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    for match_index, card in enumerate(match_cards):
        league_name = card.get("leagueName")
        for signal in card.get("modelSignals") or []:
            if not isinstance(signal, Mapping):
                continue
            if isinstance(model_name := signal.get("modelName"), str) and model_name:
                models[model_name].append((match_index, signal))
            if isinstance(play_type := signal.get("playType"), str) and play_type:
                play_types[play_type].append((match_index, signal))
            if isinstance(league_name, str) and league_name:
                leagues[league_name].append((match_index, signal))
    return {
        "models": _sort_breakdown(
            [_signal_breakdown_row(key, signals) for key, signals in models.items()]
        ),
        "playTypes": _sort_breakdown(
            [_signal_breakdown_row(key, signals) for key, signals in play_types.items()]
        ),
        "leagues": _sort_breakdown(
            [_signal_breakdown_row(key, signals) for key, signals in leagues.items()]
        ),
    }


def build_periodic_research_breakdowns(
    daily_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge daily frozen signal distributions while retaining sparse history."""
    result: dict[str, list[dict[str, Any]]] = {}
    for category in ("models", "playTypes", "leagues"):
        grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for snapshot in daily_snapshots:
            breakdowns = snapshot.get("researchBreakdowns")
            if not isinstance(breakdowns, Mapping):
                continue
            for row in breakdowns.get(category) or []:
                if isinstance(row, Mapping) and isinstance(row.get("key"), str):
                    grouped[row["key"]].append(row)
        merged_rows: list[dict[str, Any]] = []
        for key, rows in grouped.items():
            signal_count = sum(int(_number(row.get("signalCount")) or 0) for row in rows)
            match_count = sum(int(_number(row.get("matchCount")) or 0) for row in rows)

            def weighted_average(
                metric_key: str,
                group_rows: Sequence[Mapping[str, Any]] = rows,
            ) -> float | None:
                weighted = [
                    (value, int(_number(row.get("signalCount")) or 0))
                    for row in group_rows
                    if (value := _number(row.get(metric_key))) is not None
                    and int(_number(row.get("signalCount")) or 0) > 0
                ]
                total_weight = sum(weight for _value, weight in weighted)
                return (
                    round(sum(value * weight for value, weight in weighted) / total_weight, 4)
                    if total_weight
                    else None
                )

            merged_rows.append(
                {
                    "key": key,
                    "signalCount": signal_count,
                    "matchCount": match_count,
                    "averageModelProbability": weighted_average("averageModelProbability"),
                    "averageMarketProbability": weighted_average("averageMarketProbability"),
                    "averageEdge": weighted_average("averageEdge"),
                    "averageEv": weighted_average("averageEv"),
                }
            )
        result[category] = _sort_breakdown(merged_rows)
    return result


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
        value for signal in signals if (value := _number(signal.get("ev"))) is not None
    ]
    match_count = len(match_cards)
    signal_match_count = sum(bool(card.get("modelSignals")) for card in match_cards)
    evidence_match_count = sum(bool(card.get("evidence")) for card in match_cards)

    return {
        "matchCount": match_count,
        "signalMatchCount": signal_match_count,
        "signalCoverageRate": round(signal_match_count / match_count, 4) if match_count else 0.0,
        "evidenceMatchCount": evidence_match_count,
        "evidenceCoverageRate": round(evidence_match_count / match_count, 4)
        if match_count
        else 0.0,
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


def build_periodic_research_metrics(
    daily_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate already-frozen daily research metrics for a closed period.

    The aggregation remains descriptive: it reports historical coverage and
    signal characteristics, and does not re-score a prediction or alter facts.
    Older daily snapshots without ``researchMetrics`` remain valid inputs.
    """
    metric_rows: list[Mapping[str, Any]] = []
    for snapshot in daily_snapshots:
        metrics = snapshot.get("researchMetrics")
        if isinstance(metrics, Mapping):
            metric_rows.append(metrics)
    match_count = sum(int(_number(row.get("matchCount")) or 0) for row in metric_rows)
    signal_count = sum(int(_number(row.get("signalCount")) or 0) for row in metric_rows)
    signal_match_count = sum(int(_number(row.get("signalMatchCount")) or 0) for row in metric_rows)
    evidence_match_count = sum(
        int(_number(row.get("evidenceMatchCount")) or 0) for row in metric_rows
    )

    def weighted_average(key: str) -> float | None:
        weighted = [
            (value, int(_number(row.get("signalCount")) or 0))
            for row in metric_rows
            if (value := _number(row.get(key))) is not None
            and int(_number(row.get("signalCount")) or 0) > 0
        ]
        total_weight = sum(weight for _value, weight in weighted)
        return (
            round(sum(value * weight for value, weight in weighted) / total_weight, 4)
            if total_weight
            else None
        )

    return {
        "dailyReportCount": len(daily_snapshots),
        "researchMetricDayCount": len(metric_rows),
        "matchCount": match_count,
        "signalCount": signal_count,
        "signalMatchCount": signal_match_count,
        "signalCoverageRate": round(signal_match_count / match_count, 4) if match_count else 0.0,
        "evidenceMatchCount": evidence_match_count,
        "evidenceCoverageRate": (
            round(evidence_match_count / match_count, 4) if match_count else 0.0
        ),
        "averageModelProbability": weighted_average("averageModelProbability"),
        "averageMarketProbability": weighted_average("averageMarketProbability"),
        "averageEdge": weighted_average("averageEdge"),
        "averageEv": weighted_average("averageEv"),
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
        {field: deepcopy(card.get(field)) for field in _MATCH_CARD_FIELDS} for card in match_cards
    ]
    performance = build_daily_performance(match_cards)
    upset_metrics = upset_report.get("metrics") if isinstance(upset_report, Mapping) else None
    upset_summary = (
        deepcopy(dict(upset_metrics.get("upsets") or {}))
        if isinstance(upset_metrics, Mapping)
        else {}
    )
    return {
        "schemaVersion": 4,
        "sourceNotice": (
            "比赛、赛果、赛前模型信号和官方赔率均由后端只读归档；"
            "证据缺失时明确标记为未查到可靠资料。"
        ),
        "dailyReview": deepcopy(dict(review)),
        "researchMetrics": build_daily_research_metrics(review, match_cards),
        "researchBreakdowns": build_daily_research_breakdowns(match_cards),
        **performance,
        "matches": matches,
        "upsetReport": deepcopy(dict(upset_report)),
        "upsetSummary": upset_summary,
    }
