"""Conservative, advisory-only review gate for calibration profiles."""

from __future__ import annotations

from typing import Any

MANUAL_REVIEW_SAMPLE_THRESHOLD = 300
MANUAL_REVIEW_IMPROVEMENT_THRESHOLD = 0.005
TREND_STABILITY_THRESHOLD = 0.002
COMPARABLE_SAMPLE_RATIO_MINIMUM = 0.8


def review_calibration_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Describe whether a shadow profile merits human review, never promotion."""
    sample_count = int(profile["sample_count"])
    improvement = float(profile["log_loss_before"]) - float(profile["log_loss_after"])
    ready = (
        sample_count >= MANUAL_REVIEW_SAMPLE_THRESHOLD
        and improvement >= MANUAL_REVIEW_IMPROVEMENT_THRESHOLD
    )
    return {
        "status": "ready_for_manual_review" if ready else "observing",
        "label": "可人工评审" if ready else "持续观察",
        "sampleThreshold": MANUAL_REVIEW_SAMPLE_THRESHOLD,
        "improvementThreshold": MANUAL_REVIEW_IMPROVEMENT_THRESHOLD,
        "logLossImprovement": round(improvement, 6),
        "affectsDecisionPath": False,
    }


def review_calibration_trend(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recent shadow loss movement for human review only."""
    ordered = sorted(profiles, key=lambda profile: str(profile["created_at"]))
    latest_loss = float(ordered[-1]["log_loss_after"])
    if len(ordered) == 1:
        return {
            "status": "insufficient_history",
            "label": "历史不足",
            "latestLogLoss": latest_loss,
            "previousLogLoss": None,
            "logLossChange": None,
            "profileCount": 1,
            "comparison": {
                "status": "insufficient_history",
                "label": "历史不足",
                "sampleRatio": None,
            },
            "affectsDecisionPath": False,
        }

    previous_loss = float(ordered[-2]["log_loss_after"])
    previous_samples = int(ordered[-2]["sample_count"])
    latest_samples = int(ordered[-1]["sample_count"])
    sample_ratio = round(latest_samples / previous_samples, 6)
    comparable = COMPARABLE_SAMPLE_RATIO_MINIMUM <= sample_ratio <= (1 / COMPARABLE_SAMPLE_RATIO_MINIMUM)
    change = round(latest_loss - previous_loss, 6)
    if change <= -TREND_STABILITY_THRESHOLD:
        status, label = "improving", "近期改善"
    elif change >= TREND_STABILITY_THRESHOLD:
        status, label = "weakening", "近期退化"
    else:
        status, label = "stable", "近期稳定"
    return {
        "status": status,
        "label": label,
        "latestLogLoss": latest_loss,
        "previousLogLoss": previous_loss,
        "logLossChange": change,
        "profileCount": len(ordered),
        "comparison": {
            "status": "comparable" if comparable else "sample_changed",
            "label": "样本可比" if comparable else "样本变化较大",
            "sampleRatio": sample_ratio,
        },
        "affectsDecisionPath": False,
    }
