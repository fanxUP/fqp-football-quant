"""Promotion thresholds for News Intelligence shadow experiments."""

from __future__ import annotations

from typing import Any

MIN_PROMOTION_SAMPLES = 1000
MAX_BRIER_DELTA = -0.005
MAX_LOG_LOSS_DELTA = 0.0


def assess_promotion(
    *,
    sample_size: int,
    brier_delta: float | None,
    log_loss_delta: float | None,
) -> dict[str, Any]:
    if sample_size < MIN_PROMOTION_SAMPLES:
        return {
            "eligible": False,
            "reason": f"已结算样本少于 {MIN_PROMOTION_SAMPLES} 场",
        }
    if brier_delta is None or brier_delta > MAX_BRIER_DELTA:
        return {
            "eligible": False,
            "reason": f"Brier 改善幅度未达到 {abs(MAX_BRIER_DELTA):.3f}",
        }
    if log_loss_delta is None or log_loss_delta > MAX_LOG_LOSS_DELTA:
        return {"eligible": False, "reason": "Log Loss 不得退化"}
    return {"eligible": True, "reason": "已达到人工晋升门槛"}
