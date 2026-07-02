"""传统足彩组合覆盖简化骨架。生产版需要蒙特卡洛模拟与奖池估计。"""

from __future__ import annotations

from itertools import product


def expand_choices(match_choices: list[list[str]], max_units: int = 250) -> list[tuple]:
    units = []
    for combo in product(*match_choices):
        units.append(combo)
        if len(units) >= max_units:
            break
    return units


def choose_rx9(matches: list[dict]) -> list[dict]:
    """按不确定性和数据质量筛选任九：保留更清晰的9场。"""
    ranked = sorted(matches, key=lambda m: (m.get("uncertainty", 1), -m.get("data_quality", 0)))
    return ranked[:9]
