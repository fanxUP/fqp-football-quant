"""Conservative, advisory-only review gate for calibration profiles."""

from __future__ import annotations

from typing import Any

MANUAL_REVIEW_SAMPLE_THRESHOLD = 300
MANUAL_REVIEW_IMPROVEMENT_THRESHOLD = 0.005


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
