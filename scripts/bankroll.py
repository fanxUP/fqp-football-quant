"""资金管理工具：每日500元上限、分数Kelly、风控限制。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StakeLimits:
    daily_remaining: float = 500
    pool_remaining: float = 300
    max_ticket_stake: float = 100
    max_match_exposure_remaining: float = 150
    kelly_fraction: float = 0.25


def raw_kelly(probability: float, odds: float) -> float:
    if odds <= 1:
        return 0.0
    return max(0.0, (probability * odds - 1.0) / (odds - 1.0))


def suggested_stake(probability: float, odds: float, limits: StakeLimits) -> float:
    k = raw_kelly(probability, odds) * limits.kelly_fraction
    stake = limits.pool_remaining * k
    stake = min(
        stake, limits.daily_remaining, limits.max_ticket_stake, limits.max_match_exposure_remaining
    )
    return max(0.0, round(stake / 2) * 2)  # 体彩常见金额单位可按2元取整，生产以配置为准
