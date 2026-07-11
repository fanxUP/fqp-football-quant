"""推荐熔断判断。"""

from __future__ import annotations


def evaluate_shutdown(context: dict) -> list[dict]:
    reasons = []
    if not context.get("official_source_ok", False):
        reasons.append(
            {"code": "OFFICIAL_SOURCE_UNAVAILABLE", "blocking": True, "message": "官方数据源不可用"}
        )
    if context.get("data_quality_score", 100) < 80:
        reasons.append(
            {"code": "LOW_DATA_QUALITY", "blocking": True, "message": "数据完整度低于80"}
        )
    if context.get("committee_disagreement", 0) > 0.45:
        reasons.append(
            {"code": "MODEL_DISAGREEMENT", "blocking": True, "message": "模型委员会分歧过大"}
        )
    if context.get("adjusted_ev", 0) < 0.03:
        reasons.append(
            {"code": "ADJUSTED_EV_TOO_LOW", "blocking": True, "message": "不确定性惩罚后EV不足"}
        )
    if context.get("losing_days", 0) >= 7:
        reasons.append(
            {"code": "SIMULATION_ONLY", "blocking": True, "message": "连续亏损达到阈值，只输出模拟"}
        )
    return reasons
