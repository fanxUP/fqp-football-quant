"""Outcome-grounded performance metrics for immutable report snapshots.

The module only scores frozen, pre-kickoff model signals against confirmed
official results and the last available official odds.  It never writes model,
ticket, recommendation, or risk-control records.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

_PLAY_ALIASES = {"score": "bf", "total_goals": "zjq", "half_full": "bqc"}
_RESULT_KEYS = {
    "spf": "spfResult",
    "rqspf": "rqspfResult",
    "bf": "scoreResult",
    "zjq": "totalGoalsResult",
    "bqc": "halfFullResult",
}
_DIRECTION_OPTIONS = {
    "3": "3",
    "h": "3",
    "home": "3",
    "home_win": "3",
    "主胜": "3",
    "让球主胜": "3",
    "1": "1",
    "d": "1",
    "draw": "1",
    "平": "1",
    "平局": "1",
    "让球平": "1",
    "0": "0",
    "a": "0",
    "away": "0",
    "away_win": "0",
    "客胜": "0",
    "主负": "0",
    "让球客胜": "0",
}
_ERROR_LABELS = {
    "MODEL_OVERCONFIDENCE": "模型过度自信",
    "DRAW_UNDERESTIMATED": "低估平局",
    "FAVOURITE_DIRECTION_REVERSED": "胜负方向反转",
    "POSITIVE_EV_MISSED": "正EV未兑现",
    "PREDICTION_MISS": "一般预测偏差",
}
_ERROR_ACTIONS = {
    "MODEL_OVERCONFIDENCE": "复核高概率区间的校准误差，降低未经充分证据支持的置信度。",
    "DRAW_UNDERESTIMATED": "复核低比分和平局先验，并检查临场阵容与节奏证据。",
    "FAVOURITE_DIRECTION_REVERSED": "复核球队强弱、主客场修正及临场赔率方向。",
    "POSITIVE_EV_MISSED": "复核推荐时点与休市赔率之间的数据时效差异。",
    "PREDICTION_MISS": "继续积累同类样本，避免根据单场结果调整模型。",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _average(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _play_type(value: Any) -> str:
    code = str(value or "").lower()
    return _PLAY_ALIASES.get(code, code)


def _option(play_type: str, value: Any) -> str:
    raw = str(value or "").strip()
    if play_type in {"spf", "rqspf"}:
        return _DIRECTION_OPTIONS.get(raw.lower(), _DIRECTION_OPTIONS.get(raw, raw))
    if play_type == "bqc":
        return raw.replace("-", "")
    return raw


def _actual_option(card: Mapping[str, Any], play_type: str, options: set[str]) -> str | None:
    result = card.get("result")
    if not isinstance(result, Mapping):
        return None
    key = _RESULT_KEYS.get(play_type)
    if not key:
        return None
    actual = _option(play_type, result.get(key))
    if play_type == "bf" and actual and actual not in options and ":" in actual:
        try:
            home, away = (int(value) for value in actual.split(":", 1))
        except ValueError:
            return None
        actual = "other_h" if home > away else "other_d" if home == away else "other_a"
    return actual or None


def _closing_market(card: Mapping[str, Any], play_type: str) -> dict[str, dict[str, float]]:
    prices: dict[str, float] = {}
    for row in card.get("oddsSignals") or []:
        if not isinstance(row, Mapping) or _play_type(row.get("playType")) != play_type:
            continue
        option = _option(play_type, row.get("optionCode"))
        odd = _number(row.get("spValue"))
        if option and odd is not None and odd > 1:
            prices[option] = odd
    inverse_total = sum(1 / odd for odd in prices.values())
    if inverse_total <= 0:
        return {}
    return {
        option: {"odds": odd, "probability": (1 / odd) / inverse_total}
        for option, odd in prices.items()
    }


def _brier(probabilities: Mapping[str, float], actual: str) -> float:
    return sum(
        (probability - (1.0 if option == actual else 0.0)) ** 2
        for option, probability in probabilities.items()
    )


def _log_loss(probabilities: Mapping[str, float], actual: str) -> float:
    probability = max(1e-15, min(1 - 1e-15, probabilities.get(actual, 0.0)))
    return -math.log(probability)


def _rps(probabilities: Mapping[str, float], actual: str) -> float | None:
    if set(probabilities) != {"3", "1", "0"}:
        return None
    cumulative_prediction = 0.0
    cumulative_actual = 0.0
    total = 0.0
    for option in ("3", "1", "0"):
        cumulative_prediction += probabilities[option]
        cumulative_actual += 1.0 if option == actual else 0.0
        total += (cumulative_prediction - cumulative_actual) ** 2
    return total / 2


def _sample_groups(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for signal in card.get("modelSignals") or []:
        if not isinstance(signal, Mapping):
            continue
        model = str(signal.get("modelName") or "").strip()
        play_type = _play_type(signal.get("playType"))
        if model and play_type:
            grouped[(model, play_type)].append(signal)

    samples: list[dict[str, Any]] = []
    for (model, play_type), signals in grouped.items():
        raw_probabilities: dict[str, float] = {}
        market_probabilities: dict[str, float] = {}
        expected_values: dict[str, float] = {}
        for signal in signals:
            option = _option(play_type, signal.get("optionCode"))
            probability = _number(signal.get("modelProbability"))
            if not option or probability is None or probability < 0:
                continue
            raw_probabilities[option] = probability
            if (market := _number(signal.get("marketProbability"))) is not None:
                market_probabilities[option] = market
            if (expected_value := _number(signal.get("ev"))) is not None:
                expected_values[option] = expected_value
        probability_total = sum(raw_probabilities.values())
        if probability_total <= 0:
            continue
        probabilities = {
            option: probability / probability_total
            for option, probability in raw_probabilities.items()
        }
        actual = _actual_option(card, play_type, set(probabilities))
        if actual is None or actual not in probabilities:
            continue
        predicted = max(probabilities, key=lambda option: (probabilities[option], option))
        correct = predicted == actual
        closing = _closing_market(card, play_type)
        closing_pick = closing.get(predicted)
        closing_probability = closing_pick["probability"] if closing_pick else None
        closing_odds = closing_pick["odds"] if closing_pick else None
        prediction_market = market_probabilities.get(predicted)
        clv = (
            closing_probability - prediction_market
            if closing_probability is not None and prediction_market is not None
            else None
        )
        closing_edge = (
            probabilities[predicted] - closing_probability
            if closing_probability is not None
            else None
        )
        unit_profit = (closing_odds - 1 if correct else -1.0) if closing_odds else None
        evidence = [row for row in (card.get("evidence") or []) if isinstance(row, Mapping)]
        samples.append(
            {
                "matchId": card.get("matchId"),
                "kickoffTime": card.get("kickoffTime"),
                "leagueName": str(card.get("leagueName") or "未知联赛"),
                "modelName": model,
                "playType": play_type,
                "predictedOption": predicted,
                "actualOption": actual,
                "modelProbability": round(probabilities[predicted], 8),
                "predictionMarketProbability": prediction_market,
                "closingProbability": closing_probability,
                "closingOdds": closing_odds,
                "clv": clv,
                "closingEdge": closing_edge,
                "ev": expected_values.get(predicted),
                "isCorrect": correct,
                "brierScore": _brier(probabilities, actual),
                "logLoss": _log_loss(probabilities, actual),
                "rps": _rps(probabilities, actual),
                "unitStakeProfit": unit_profit,
                "hasEvidence": bool(evidence),
            }
        )
    return samples


def _calibration(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bins: list[dict[str, Any]] = []
    total_error = 0.0
    maximum_error = 0.0
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        upper = lower + 0.2
        rows = [
            row
            for row in samples
            if (probability := _number(row.get("modelProbability"))) is not None
            and lower <= probability <= (upper if upper == 1.0 else upper - 1e-12)
        ]
        if not rows:
            continue
        predicted = sum(float(row["modelProbability"]) for row in rows) / len(rows)
        actual = sum(1 for row in rows if row.get("isCorrect")) / len(rows)
        error = abs(predicted - actual)
        total_error += error * len(rows)
        maximum_error = max(maximum_error, error)
        bins.append(
            {
                "lower": lower,
                "upper": round(upper, 1),
                "sampleCount": len(rows),
                "averageProbability": round(predicted, 6),
                "actualRate": round(actual, 6),
            }
        )
    return {
        "bins": bins,
        "ece": round(total_error / len(samples), 6) if samples else None,
        "mce": round(maximum_error, 6) if samples else None,
    }


def _streaks(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        samples,
        key=lambda row: (
            str(row.get("kickoffTime") or ""),
            str(row.get("matchId") or ""),
            str(row.get("modelName") or ""),
            str(row.get("playType") or ""),
        ),
    )
    longest_loss = 0
    current_loss = 0
    streak_type: str | None = None
    streak_count = 0
    for row in ordered:
        is_correct = bool(row.get("isCorrect"))
        current_loss = 0 if is_correct else current_loss + 1
        longest_loss = max(longest_loss, current_loss)
        row_type = "win" if is_correct else "loss"
        if row_type == streak_type:
            streak_count += 1
        else:
            streak_type = row_type
            streak_count = 1
    return {
        "maxLosingStreak": longest_loss,
        "currentStreakType": streak_type,
        "currentStreakCount": streak_count if streak_type else 0,
    }


def _metrics(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sample_count = len(samples)
    correct_count = sum(1 for row in samples if row.get("isCorrect"))
    priced = [row for row in samples if _number(row.get("unitStakeProfit")) is not None]
    unit_profit = round(sum(float(row["unitStakeProfit"]) for row in priced), 4)
    calibration = _calibration(samples)
    return {
        "sampleCount": sample_count,
        "correctCount": correct_count,
        "hitRate": round(correct_count / sample_count, 6) if sample_count else None,
        "brierScore": _average([float(row["brierScore"]) for row in samples]),
        "logLoss": _average([float(row["logLoss"]) for row in samples]),
        "rps": _average(
            [float(value) for row in samples if (value := _number(row.get("rps"))) is not None]
        ),
        "clvSampleCount": sum(_number(row.get("clv")) is not None for row in samples),
        "averageClv": _average(
            [float(value) for row in samples if (value := _number(row.get("clv"))) is not None]
        ),
        "averageClosingEdge": _average(
            [
                float(value)
                for row in samples
                if (value := _number(row.get("closingEdge"))) is not None
            ]
        ),
        "averageClosingOdds": _average(
            [
                float(value)
                for row in samples
                if (value := _number(row.get("closingOdds"))) is not None
            ]
        ),
        "pricedSampleCount": len(priced),
        "unitStakeProfit": unit_profit,
        "unitStakeRoi": round(unit_profit / len(priced), 6) if priced else None,
        "calibrationError": calibration["ece"],
        "maximumCalibrationError": calibration["mce"],
        "calibrationBins": calibration["bins"],
        **_streaks(samples),
    }


def _breakdown_rows(samples: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.get(key) or "未知")].append(sample)
    rows = [{"key": group_key, **_metrics(group)} for group_key, group in grouped.items()]
    return sorted(rows, key=lambda row: (-row["sampleCount"], row["key"]))


def _errors(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    items = []
    for row in samples:
        if row.get("isCorrect"):
            continue
        probability = float(row.get("modelProbability") or 0)
        predicted = str(row.get("predictedOption") or "")
        actual = str(row.get("actualOption") or "")
        code: str
        if probability >= 0.60:
            code = "MODEL_OVERCONFIDENCE"
        elif actual == "1" and predicted != "1":
            code = "DRAW_UNDERESTIMATED"
        elif {predicted, actual} == {"3", "0"}:
            code = "FAVOURITE_DIRECTION_REVERSED"
        elif float(row.get("ev") or 0) > 0.03:
            code = "POSITIVE_EV_MISSED"
        else:
            code = "PREDICTION_MISS"
        items.append(
            {
                "code": code,
                "label": _ERROR_LABELS[code],
                "matchId": row.get("matchId"),
                "modelName": row.get("modelName"),
                "playType": row.get("playType"),
                "predictedOption": predicted,
                "actualOption": actual,
                "modelProbability": probability,
                "suggestedAction": _ERROR_ACTIONS[code],
            }
        )
    counts: Counter[str] = Counter(str(item["code"]) for item in items)
    by_type = [
        {
            "code": code,
            "label": _ERROR_LABELS[code],
            "count": count,
            "suggestedAction": _ERROR_ACTIONS[code],
        }
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"errorCount": len(items), "byType": by_type, "items": items[:50]}


def _evidence(cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        evidence
        for card in cards
        for evidence in (card.get("evidence") or [])
        if isinstance(evidence, Mapping)
    ]
    covered = sum(bool(card.get("evidence")) for card in cards)

    def phase(row: Mapping[str, Any]) -> str:
        return str(row.get("phase") or "").lower().replace("-", "_")

    def source(row: Mapping[str, Any]) -> str:
        return f"{row.get('sourceType') or ''} {row.get('sourceName') or ''}".lower()

    return {
        "evidenceCount": len(rows),
        "coveredMatchCount": covered,
        "preMatchCount": sum(phase(row) in {"pre_match", "prematch"} for row in rows),
        "postMatchCount": sum(phase(row) in {"post_match", "postmatch"} for row in rows),
        "newsEvidenceCount": sum("news" in source(row) or "新闻" in source(row) for row in rows),
        "officialOrVerifiedCount": sum(
            str(row.get("reliability") or "").lower() in {"official", "verified"} for row in rows
        ),
        "missingMatchCount": max(0, len(cards) - covered),
    }


def _strategy(
    metrics: Mapping[str, Any], errors: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    findings: list[str] = []
    actions: list[str] = []
    samples = int(metrics.get("sampleCount") or 0)
    if samples < 30:
        findings.append(f"当前仅有 {samples} 个可评估模型选择，结论仍受小样本影响。")
    if metrics.get("calibrationError") is not None:
        findings.append(f"概率校准误差 ECE 为 {float(metrics['calibrationError']):.2%}。")
    if metrics.get("averageClv") is not None:
        findings.append(f"平均 CLV 为 {float(metrics['averageClv']):+.2%}。")
    if errors.get("byType"):
        leading = errors["byType"][0]
        findings.append(f"主要错因是{leading['label']}（{leading['count']}次）。")
        actions.append(str(leading["suggestedAction"]))
    if int(evidence.get("newsEvidenceCount") or 0) == 0:
        actions.append("本期没有可靠新闻来源，涉及阵容、伤停和赛后事件的解释必须保持未核验。")
    actions.append("仅在样本持续积累后复核模型，不根据单场输赢自动改动预测、投注或风控。")
    return {
        "status": "review_required"
        if errors.get("errorCount") or evidence.get("missingMatchCount")
        else "observed",
        "findings": findings,
        "actions": actions,
        "safetyNotice": "该总结只用于人工研究复盘，不会自动修改模型、推荐、投注或风控。",
    }


def build_daily_performance(match_cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Score one immutable day from confirmed results and pre-kickoff signals."""
    samples = [sample for card in match_cards for sample in _sample_groups(card)]
    metrics = _metrics(samples)
    errors = _errors(samples)
    evidence = _evidence(match_cards)
    return {
        "performanceMetrics": metrics,
        "performanceBreakdowns": {
            "models": _breakdown_rows(samples, "modelName"),
            "playTypes": _breakdown_rows(samples, "playType"),
            "leagues": _breakdown_rows(samples, "leagueName"),
        },
        "errorAnalysis": errors,
        "evidenceSummary": evidence,
        "strategySummary": _strategy(metrics, errors, evidence),
        "performanceSeries": samples,
    }


def build_periodic_performance(daily_snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge frozen daily samples; never query or re-score mutable business tables."""
    samples = [
        sample
        for snapshot in daily_snapshots
        for sample in (snapshot.get("performanceSeries") or [])
        if isinstance(sample, Mapping)
    ]
    metrics = _metrics(samples)
    errors = _errors(samples)
    evidence_fields = (
        "evidenceCount",
        "coveredMatchCount",
        "preMatchCount",
        "postMatchCount",
        "newsEvidenceCount",
        "officialOrVerifiedCount",
        "missingMatchCount",
    )
    evidence = {
        field: sum(
            int((snapshot.get("evidenceSummary") or {}).get(field) or 0)
            for snapshot in daily_snapshots
            if isinstance(snapshot.get("evidenceSummary"), Mapping)
        )
        for field in evidence_fields
    }
    return {
        "performanceMetrics": metrics,
        "performanceBreakdowns": {
            "models": _breakdown_rows(samples, "modelName"),
            "playTypes": _breakdown_rows(samples, "playType"),
            "leagues": _breakdown_rows(samples, "leagueName"),
        },
        "errorAnalysis": errors,
        "evidenceSummary": evidence,
        "strategySummary": _strategy(metrics, errors, evidence),
        "performanceSeries": samples,
    }
