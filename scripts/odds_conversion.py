"""赔率转概率工具。
生产使用前必须结合官方SP历史数据验证。

提供三种去水方法:
  1. normalize_probabilities  — 比例法（最简单，当前默认）
  2. power_method             — 幂指数法
  3. shin_method              — Shin (1993) 知情交易者模型（推荐）
"""

from __future__ import annotations

import math


def implied_probabilities(odds: dict[str, float]) -> dict[str, float]:
    """计算原始隐含概率 b_i = 1/o_i"""
    return {k: 1.0 / v for k, v in odds.items() if v and v > 0}


def normalize_probabilities(odds: dict[str, float]) -> dict[str, float]:
    """比例法去水：简单地将各选项隐含概率按比例归一化到 sum=1。

    优点：最简单，始终有解析解
    缺点：假设庄家在各选项上加的 spread 比例相同（通常不成立）
    """
    raw = implied_probabilities(odds)
    s = sum(raw.values())
    if s <= 0:
        raise ValueError("赔率无效，无法归一化")
    return {k: v / s for k, v in raw.items()}


def power_method(odds: dict[str, float], power: float = 1.0) -> dict[str, float]:
    """幂指数法去水：b_i = (1/o_i)^power，然后归一化。

    power < 1 时缩小概率差距（适合减少 FLB 偏差），
    power > 1 时放大差距。默认 power=1 退化为比例法。
    """
    raw = {k: (1.0 / v) ** power for k, v in odds.items() if v and v > 0}
    s = sum(raw.values())
    if s <= 0:
        raise ValueError("赔率无效")
    return {k: v / s for k, v in raw.items()}


def shin_method(odds: dict[str, float]) -> dict[str, float]:
    r"""Shin (1993) 知情交易者模型去水。

    模型假设市场中存在比例 z 的知情交易者（insider），
    庄家为了保护自己会对冷门方向加更多 spread。
    z 越大 → 冷门被"挤出"越多 → 热门/冷门的概率差异更大。

    公式：
      b_i = 1/o_i  (原始隐含概率，未经归一化)
      S   = sum(b_i) > 1  (overround 存在)

      p_i(z) = [sqrt(z² + 4(1-z)·b_i²/S²) - z] / [2(1-z)]

    关键：使用 b_i² 而非 (b_i/S)²，这样 z=0 时:
      p_i = sqrt(4·b_i²/S²) / 2 = b_i/S
      sum(p_i) = S/S = 1  ← 退化为比例法

    z > 0 时 Shin 方法对冷门施加更强的"挤出"效应。

    引用：Shin, H. S. (1993). "Measuring the Incidence of Insider Trading
    in a Market for State-Contingent Claims." Economic Journal,
    103(420), 1178-1194.
    """
    if len(odds) < 2:
        raise ValueError("Shin 方法需要至少 2 个选项")
    if len(odds) > 5:
        raise ValueError("Shin 方法当前最多支持 5 个选项")

    keys = list(odds.keys())
    b_vec = [1.0 / odds[k] for k in keys]
    S = sum(b_vec)

    if S <= 0:
        raise ValueError("赔率无效")

    # overround 极小 → 退化为比例法
    if abs(S - 1.0) < 1e-6:
        result = {k: v / S for k, v in zip(keys, b_vec, strict=False)}
        return result

    # —— 用二分法找 z 使得 sum(p_i(z)) = S ——
    # 注意：不是 sum(p_i) = 1，而是 S 修正版本。
    # 实际上，让我们重新推导。
    #
    # 在 Shin 的原始公式中，p_i(z) 总是归一化的（sum=1 对任意 z）。
    # z 由 overround 决定。正确的数值求解目标：
    #   定义 the "normalized" Shin prob:
    #     p_i(z) = [sqrt(z² + 4(1-z)b_i²) - z] / [2(1-z)] / sum_j[same for j]
    #
    # 等价的更简洁实现（Jensen 2020 的方法）：
    #   直接用 scipy.optimize 解 sum(p_i(z)) = 1，其中：
    #     p_i(z) = b_i / (S * (1-z) + z * b_i/avg_b)
    #
    # 实际上最可靠的方式是使用迭代公式。

    z = _solve_shin_z(b_vec, S)

    # —— 计算最终概率 ——
    probs = []
    for b in b_vec:
        # 使用 b_i 而不是 b_i/S
        disc = math.sqrt(z * z + 4.0 * (1.0 - z) * b * b)
        pi = (disc - z) / (2.0 * (1.0 - z))
        probs.append(max(0.0, pi))

    # 归一化
    p_sum = sum(probs)
    if p_sum > 0:
        probs = [p / p_sum for p in probs]

    result = dict(zip(keys, probs, strict=False))
    return result


def _solve_shin_z(
    b_vec: list[float],
    S: float,
    z_max: float = 0.999,
    max_iter: int = 80,
    tol: float = 1e-10,
) -> float:
    """Shin 参数 z 数值求解。

    方法：直接解 sum(p_i(z)) = 1，其中 p_i 使用 b_i（非归一化 b_i/S）。

    f(z) = sum_i [sqrt(z² + 4(1-z)b_i²) - z] / [2(1-z)] - 1

    在 z=0 处: p_i = b_i, sum = S > 1, 所以 f(0) = S - 1 > 0
    随着 z 增大，分母 2(1-z) 增大，sum 递减
    在某个 z* 处 sum = 1，f(z*) = 0
    """

    def f(z_val: float) -> float:
        """f(z) = sum(p_i(z)) - 1, 需 f(z) > 0 at z=0, monotonically decreasing"""
        if z_val <= 0.0 or z_val >= 1.0:
            # z=0: return S - 1
            if z_val <= 0.0:
                return S - 1.0
            return -1e10  # z near 1 → sum → 0, f → -1
        total = 0.0
        for b in b_vec:
            disc = math.sqrt(z_val * z_val + 4.0 * (1.0 - z_val) * b * b)
            pi = (disc - z_val) / (2.0 * (1.0 - z_val))
            total += max(0.0, pi)
        return total - 1.0

    # f(0) = S - 1 > 0
    f0 = S - 1.0

    if f0 <= tol:
        # overround ≈ 0, 无需去水
        return 0.0

    # f(z_max) < 0 (概率随 z 增大而减小)
    f_high = f(z_max)

    if f_high >= 0:
        # 即使 z 很大，sum 仍 ≥ 1  → 退化
        return 0.0

    # 二分法：f(0) > 0, f(z_max) < 0
    lo, hi = 0.0, z_max

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)

        if abs(f_mid) < tol:
            return mid

        if f_mid > 0:
            lo = mid
        else:
            hi = mid

        if abs(hi - lo) < tol:
            return (lo + hi) / 2.0

    return (lo + hi) / 2.0


def overround(odds: dict[str, float]) -> float:
    """计算 overround（庄家 margin）= sum(1/o_i) - 1"""
    return sum(1.0 / v for v in odds.values() if v and v > 0) - 1.0


def expected_value(probability: float, sp: float) -> float:
    """期望收益 = p * odds - 1"""
    return probability * sp - 1.0


# ——— Favourite-Longshot Bias 修正 ———


def correct_favourite_longshot_bias(
    probs: dict[str, float],
    odds: dict[str, float],
    exponent: float = 1.15,
) -> dict[str, float]:
    r"""Favourite-Longshot Bias (FLB) 修正。

    FLB 指博彩市场中冷门被系统性高估（隐含概率过高，赔率过低）、
    热门被系统性低估（隐含概率过低）的现象。

    修正方法（两种策略，取平均）：

    策略 A — Power-law 校正：
      p'_i = p_i^alpha / sum(p_j^alpha)
      alpha > 1 增大热门概率、压低冷门概率（FLB修正方向）

    策略 B — Odds-ratio 校正：
      p''_i = odds_i^(-alpha) / sum(odds_j^(-alpha))
      与策略A使用相同的 alpha

    最终 p_final = (p' + p'') / 2

    参数 exponent (alpha) 含义：
      - alpha = 1.0 → 不修正
      - alpha > 1.0 → 热门更热、冷门更冷（FLB 修正方向）
      - 默认 1.15 基于文献综述（Cain, Law & Peel 2003: 英国足球市场）
      - 理想值应通过 calibrate_flb_exponent() 从历史回测数据拟合

    注意：
      - 修正应用于已去水的概率（推荐先用 Shin 方法去水）
    """
    if exponent <= 0:
        raise ValueError(f"exponent must be > 0, got {exponent}")

    keys = list(probs.keys())
    p_vec = [probs[k] for k in keys]

    # 策略 A: Power-law on probabilities (alpha > 1 → 放大差异)
    p_pow = [p**exponent for p in p_vec]
    s_pow = sum(p_pow)
    p_a = [v / s_pow for v in p_pow]

    # 策略 B: Odds-ratio correction
    # p ∝ 1/odds → p'' ∝ (1/odds)^exponent = odds^(-exponent)
    odds_inv_pow = [odds[k] ** (-exponent) for k in keys]
    s_odds = sum(odds_inv_pow)
    p_b = [v / s_odds for v in odds_inv_pow]

    # 两种策略取平均
    p_final = [(pa + pb) / 2.0 for pa, pb in zip(p_a, p_b, strict=False)]

    # 归一化
    sf = sum(p_final)
    if sf > 0:
        p_final = [p / sf for p in p_final]

    return dict(zip(keys, p_final, strict=False))


def calibrate_flb_exponent(
    historical: list[tuple[float, int]],
    exponent_range: tuple[float, float] = (0.5, 1.2),
    steps: int = 50,
) -> tuple[float, float]:
    """从历史数据校准 FLB 指数。

    Args:
        historical: [(implied_prob, actual_outcome), ...] 的列表
                    implied_prob: 市场隐含概率 (0-1)
                    actual_outcome: 0 或 1
        exponent_range: 搜索范围 (min, max)
        steps: 搜索步数

    Returns:
        (best_exponent, best_brier_score)
    """
    if len(historical) < 10:
        return (1.15, float("inf"))  # 数据不足，返回默认值

    best_exp = 1.15
    best_brier = float("inf")

    for i in range(steps + 1):
        exp = exponent_range[0] + (exponent_range[1] - exponent_range[0]) * i / steps
        # 计算 Brier score
        squared_errors = []
        for implied_p, actual in historical:
            # 用 power-law 修正 implied_p
            corrected_p = implied_p**exp
            # 这里简化：不做跨选项归一化（单选项评估）
            # 实际上 Brier score 针对完整概率分布
            # 简化版用单选项
            se = (corrected_p - actual) ** 2
            squared_errors.append(se)
        brier = sum(squared_errors) / len(squared_errors)

        if brier < best_brier:
            best_brier = brier
            best_exp = exp

    return (best_exp, best_brier)


# ——— 完整去水 + 偏差修正流水线 ———


def full_debias_pipeline(
    odds: dict[str, float],
    flb_exponent: float = 1.15,
) -> dict[str, dict[str, float]]:
    """完整去水 + FLB修正流水线。

    步骤：
      1. Shin 方法去水（比比例法更准确地移除庄家 margin）
      2. FLB 修正（纠正冷门高估、热门低估）

    Returns:
        {"shin": {...}, "flb_corrected": {...}}
    """
    shin_probs = shin_method(odds)
    flb_probs = correct_favourite_longshot_bias(shin_probs, odds, exponent=flb_exponent)
    return {"shin": shin_probs, "flb_corrected": flb_probs}


# ——— 批量处理工具 ———


def compare_methods(odds: dict[str, float]) -> dict[str, dict[str, float]]:
    """对同一组赔率，执行所有去水方法并返回对比结果。"""
    methods: dict[str, dict[str, float]] = {}
    try:
        methods["proportional"] = normalize_probabilities(odds)
    except ValueError:
        pass
    try:
        methods["shin"] = shin_method(odds)
    except ValueError, RuntimeError:
        pass
    try:
        methods["power_0.7"] = power_method(odds, power=0.7)
    except ValueError:
        pass
    return methods


if __name__ == "__main__":
    sample = {"3": 2.10, "1": 3.20, "0": 3.00}

    print("=== 赔率样本 ===")
    print(f"  SP:   {sample}")
    print(f"  隐含: {implied_probabilities(sample)}")
    print(f"  overround: {overround(sample):.4f} ({overround(sample) * 100:.2f}%)")
    print()

    print("=== 去水方法对比 ===")
    print(f"  比例法: {normalize_probabilities(sample)}")
    try:
        print(f"  Shin:   {shin_method(sample)}")
    except Exception as e:
        print(f"  Shin:   ERROR — {e}")
    print(f"  Power(0.7): {power_method(sample, 0.7)}")
    print()

    # 展示 Shin z 值
    b_vec = [1.0 / sample[k] for k in sorted(sample.keys())]
    S = sum(b_vec)
    z = _solve_shin_z(b_vec, S)
    print(f"Shin z = {z:.6f} (~{z * 100:.2f}% insider trading)")

    # 极端赔率测试
    extreme = {"3": 1.30, "1": 6.50, "0": 12.00}
    print("\n=== 极端赔率 ===")
    print(f"  SP:   {extreme}")
    print(f"  比例法: {normalize_probabilities(extreme)}")
    try:
        print(f"  Shin:   {shin_method(extreme)}")
    except Exception as e:
        print(f"  Shin:   ERROR — {e}")
