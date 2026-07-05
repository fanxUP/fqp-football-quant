"""传统足彩 14场/任九 组合优化引擎。

覆盖 Phase 10 需求：
- 期号管理、14场比赛对阵与赔率数据
- 3/1/0 概率计算（依托现有模型 pipeline）
- 冷门指数与公众情绪代理
- 胆/拖/防守选项分类
- 预算约束下的组合压缩
- 蒙特卡洛模拟：命中14场、13场、任九概率
- 输出：组合数量、成本、理论命中率、冷门覆盖度

不与固定SP竞彩逻辑混用。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import product
from typing import Any

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PoolMatch:
    """一场传统足彩比赛的概率估计与元数据。"""

    match_id: int | None = None
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    match_date: str = ""

    # 模型估计的胜/平/负概率（已去水，和为1）
    prob_home: float = 0.33
    prob_draw: float = 0.34
    prob_away: float = 0.33

    # 市场赔率（用于冷门指数计算）
    market_odds_home: float | None = None
    market_odds_draw: float | None = None
    market_odds_away: float | None = None

    # 元特征
    uncertainty: float = 0.5  # 0-1, 越高越不确定
    data_quality: float = 0.0  # 0-1, 数据完整度
    cold_gate_index: float = 0.0  # 冷门指数，越高越可能爆冷
    public_sentiment: float = 0.5  # 0-1, 公众倾向主胜的程度
    is_derby: bool = False
    is_top_clash: bool = False

    # 胆/拖/防守分类结果
    classification: str = "normal"  # dan | tuo | defense | normal

    @property
    def max_prob(self) -> float:
        return max(self.prob_home, self.prob_draw, self.prob_away)

    @property
    def max_prob_option(self) -> str:
        mapping = {self.prob_home: "3", self.prob_draw: "1", self.prob_away: "0"}
        return mapping[self.max_prob]

    @property
    def entropy(self) -> float:
        """信息熵，衡量结果不确定性。"""
        eps = 1e-10
        return -sum(
            p * math.log2(p + eps)
            for p in [self.prob_home, self.prob_draw, self.prob_away]
            if p > 0
        )


@dataclass
class CombinationResult:
    """一组完整的14场投注组合。"""

    selections: list[str]  # 14个选项，如 ["3","1","3","0",...]
    cost: int = 2  # 单注金额（元）
    dan_count: int = 0
    tuo_count: int = 0
    defense_count: int = 0
    cold_gate_coverage: float = 0.0  # 冷门覆盖比例
    estimated_hit_prob: float = 0.0  # 蒙特卡洛估计命中概率


@dataclass
class PoolAnalysis:
    """14场/任九分析报告。"""

    period_id: str = ""
    matches: list[PoolMatch] = field(default_factory=list)

    # 胆拖防守统计
    dan_matches: list[int] = field(default_factory=list)  # match indices
    tuo_matches: list[int] = field(default_factory=list)
    defense_matches: list[int] = field(default_factory=list)

    # 组合结果
    full_combinations: list[CombinationResult] = field(default_factory=list)
    rx9_combinations: list[CombinationResult] = field(default_factory=list)

    # 蒙特卡洛估计
    mc_hit14_prob: float = 0.0
    mc_hit13_prob: float = 0.0
    mc_rx9_prob: float = 0.0
    mc_total_cost: int = 0
    mc_combinations_used: int = 0

    # 冷门覆盖
    cold_gate_coverage: float = 0.0
    max_single_exposure: float = 0.0

    # 元数据
    generated_at: str = ""
    model_version: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 胆/拖/防守分类
# ---------------------------------------------------------------------------


def classify_matches(
    matches: list[PoolMatch],
    dan_threshold: float = 0.55,
    cold_threshold: float = 0.35,
    min_dan: int = 3,
    max_dan: int = 7,
) -> list[PoolMatch]:
    """将14场比赛分类为胆（anchor）、拖（flex）、防守（defense）。

    胆：高置信度比赛，模型概率 ≥ dan_threshold 且冷门指数低
    拖：中等置信度，可灵活选择
    防守：冷门风险高（cold_gate_index ≥ cold_threshold），需要考虑防冷选项

    规则：
    - 胆数量约束在 [min_dan, max_dan] 之间
    - 防守比赛至少保留一个"非热门"选项
    """
    result = []
    for m in matches:
        # 分类逻辑
        if m.max_prob >= dan_threshold and m.cold_gate_index < cold_threshold:
            m.classification = "dan"
        elif m.cold_gate_index >= cold_threshold:
            m.classification = "defense"
        else:
            m.classification = "tuo"
        result.append(m)

    # 调整胆数量到约束范围内
    dan_indices = [i for i, m in enumerate(result) if m.classification == "dan"]
    if len(dan_indices) < min_dan:
        # 从拖中挑最高置信度的补足
        candidates = sorted(
            [i for i, m in enumerate(result) if m.classification == "tuo"],
            key=lambda i: (result[i].max_prob, -result[i].cold_gate_index),
            reverse=True,
        )
        for idx in candidates[: min_dan - len(dan_indices)]:
            result[idx].classification = "dan"
    elif len(dan_indices) > max_dan:
        # 去掉置信度最低的胆
        sorted_dans = sorted(dan_indices, key=lambda i: result[i].max_prob)
        for idx in sorted_dans[: len(dan_indices) - max_dan]:
            result[idx].classification = "tuo"

    return result


# ---------------------------------------------------------------------------
# 冷门指数计算
# ---------------------------------------------------------------------------


def compute_cold_gate_index(
    match: PoolMatch,
    market_avg_prob_home: float | None = None,
) -> float:
    """综合计算冷门指数 (0-1)。

    指标因子：
    1. 市场赔率隐含的主胜概率 vs 模型主胜概率的差值（市场过度乐观）
    2. 比赛信息熵（高熵 = 高不确定性 = 爆冷潜力）
    3. 德比/强强对话额外加分
    """
    score = 0.0

    # 因子1：市场-模型分歧
    if match.market_odds_home and match.market_odds_home > 1.0:
        market_implied = 1.0 / match.market_odds_home
        divergence = abs(match.prob_home - market_implied)
        score += divergence * 0.4

    # 因子2：信息熵
    score += match.entropy / math.log2(3) * 0.3  # normalize by max entropy

    # 因子3：德比/强强对话
    if match.is_derby:
        score += 0.15
    if match.is_top_clash:
        score += 0.10

    # 因子4：数据质量越低，冷门风险越高
    score += (1.0 - match.data_quality) * 0.15

    return min(max(score, 0.0), 1.0)


# ---------------------------------------------------------------------------
# 选项扩展（核心）
# ---------------------------------------------------------------------------


def get_match_options(match: PoolMatch, strategy: str = "balanced") -> list[str]:
    """根据比赛分类和策略，返回该场比赛的可选投注选项。

    strategy:
      - conservative: 只选最可能的一个选项
      - balanced: 胆选1个选项，拖选2个，防守选2-3个
      - aggressive: 尽可能多选
      - dan_only: 只选胆的单一选项（用于胆拖组合的"胆"部分）
    """
    probs = [
        ("3", match.prob_home),
        ("1", match.prob_draw),
        ("0", match.prob_away),
    ]
    probs.sort(key=lambda x: x[1], reverse=True)

    if strategy == "conservative":
        return [probs[0][0]]
    elif strategy == "dan_only" or match.classification == "dan":
        return [probs[0][0]]
    elif match.classification == "defense":
        # 防冷：选前2或全部3个
        return [p[0] for p in probs[:2]] if strategy != "aggressive" else [p[0] for p in probs]
    elif match.classification == "tuo":
        return [p[0] for p in probs[:2]]  # 拖选前2
    elif strategy == "aggressive":
        return [p[0] for p in probs]
    else:
        return [probs[0][0]]


def expand_choices(
    match_choices: list[list[str]],
    max_units: int = 250,
    random_sample: bool = False,
) -> list[tuple[str, ...]]:
    """从选项列表生成完整组合。

    如果组合数超过 max_units，使用随机采样或提前截断。
    """
    total_size = 1
    for choices in match_choices:
        total_size *= len(choices)

    if total_size <= max_units:
        return list(product(*match_choices))

    # 超预算：随机采样
    if random_sample:
        result: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        random.seed(42)
        while len(result) < max_units:
            combo = tuple(random.choice(c) for c in match_choices)
            if combo not in seen:
                seen.add(combo)
                result.append(combo)
        return result

    # 非随机：按原始顺序截断
    units: list[tuple[str, ...]] = []
    for combo in product(*match_choices):
        units.append(combo)
        if len(units) >= max_units:
            break
    return units


# ---------------------------------------------------------------------------
# 胆拖策略优化
# ---------------------------------------------------------------------------


def dan_tuo_optimize(
    matches: list[PoolMatch],
    budget: int = 256,
    unit_cost: int = 2,
    strategy: str = "balanced",
) -> tuple[list[tuple[str, ...]], dict[str, Any]]:
    """胆拖组合优化：胆全单选，拖/防守灵活选择。

    返回：(组合列表, 统计信息)
    """
    if len(matches) < 2:
        raise ValueError(f"至少需要2场比赛，当前 {len(matches)} 场")

    classified = classify_matches(matches)
    dan_indices = [i for i, m in enumerate(classified) if m.classification == "dan"]
    tuo_indices = [i for i, m in enumerate(classified) if m.classification == "tuo"]
    defense_indices = [i for i, m in enumerate(classified) if m.classification == "defense"]

    # 胆：每个只选一个选项
    match_options: list[list[str]] = []
    for i in range(len(classified)):
        m = classified[i]
        if i in dan_indices:
            match_options.append(get_match_options(m, "dan_only"))
        elif i in defense_indices:
            match_options.append(get_match_options(m, strategy))
        else:
            match_options.append(get_match_options(m, strategy))

    # 计算最大组合数和预算约束
    max_combos = 1
    for opts in match_options:
        max_combos *= len(opts)
    budget_units = budget // unit_cost

    combos = expand_choices(match_options, max_units=min(budget_units, 5000))

    stats = {
        "dan_count": len(dan_indices),
        "tuo_count": len(tuo_indices),
        "defense_count": len(defense_indices),
        "dan_matches": [
            classified[i].home_team + " vs " + classified[i].away_team for i in dan_indices
        ],
        "defense_matches": [
            classified[i].home_team + " vs " + classified[i].away_team for i in defense_indices
        ],
        "max_possible_combos": max_combos,
        "actual_combos": len(combos),
        "total_cost": len(combos) * unit_cost,
        "budget": budget,
        "within_budget": len(combos) * unit_cost <= budget,
    }

    return combos, stats


# ---------------------------------------------------------------------------
# 任九选项
# ---------------------------------------------------------------------------


def choose_rx9(
    matches: list[PoolMatch],
    selection_method: str = "clarity",
) -> tuple[list[PoolMatch], list[int]]:
    """从14场中选出9场用于任九投注。

    selection_method:
      - clarity: 选数据质量最高、不确定性最低的9场
      - confidence: 选模型置信度最高的9场
      - mixed: 排除最不确定的2场和最可能爆冷的3场
    """
    if len(matches) < 2:
        raise ValueError(f"至少需要2场比赛，当前 {len(matches)} 场")

    if selection_method == "clarity":
        ranked = sorted(
            enumerate(matches),
            key=lambda item: (item[1].uncertainty, -item[1].data_quality),
        )
    elif selection_method == "confidence":
        ranked = sorted(
            enumerate(matches),
            key=lambda item: item[1].max_prob,
            reverse=True,
        )
    elif selection_method == "mixed":
        ranked = sorted(
            enumerate(matches),
            key=lambda item: (
                item[1].cold_gate_index * 0.4
                + item[1].uncertainty * 0.4
                - item[1].data_quality * 0.2
            ),
        )
    else:
        ranked = list(enumerate(matches))

    selected_indices = [idx for idx, _ in ranked[:9]]
    selected_matches = [matches[i] for i in selected_indices]
    return selected_matches, selected_indices


# ---------------------------------------------------------------------------
# 蒙特卡洛模拟
# ---------------------------------------------------------------------------


def monte_carlo_simulate(
    matches: list[PoolMatch],
    combinations: list[tuple[str, ...]],
    n_simulations: int = 10000,
    random_seed: int = 42,
) -> dict[str, Any]:
    """蒙特卡洛模拟：估计命中14场、13场、12场、任九的概率。

    对每场比赛按其概率分布抽样结果，然后检查每个组合的命中情况。
    """
    rng = random.Random(random_seed)
    n_matches = len(matches)
    n_combos = len(combinations)

    if n_matches == 0 or n_combos == 0:
        return {
            "hit14_prob": 0.0,
            "hit13_prob": 0.0,
            "hit12_prob": 0.0,
            "rx9_prob": 0.0,
            "expected_hits": 0.0,
            "n_simulations": n_simulations,
            "n_combinations": n_combos,
        }

    # 预计算每场比赛的选项→概率映射
    match_probs = []
    for m in matches:
        match_probs.append(
            {
                "3": m.prob_home,
                "1": m.prob_draw,
                "0": m.prob_away,
            }
        )

    hit14_count = 0
    hit13_count = 0
    hit12_count = 0
    rx9_count = 0

    for _ in range(n_simulations):
        # 模拟一场14场结果
        sim_result = []
        for probs in match_probs:
            r = rng.random()
            cumulative = 0.0
            for option, prob in [("3", probs["3"]), ("1", probs["1"]), ("0", probs["0"])]:
                cumulative += prob
                if r <= cumulative:
                    sim_result.append(option)
                    break
            else:
                sim_result.append("3")  # fallback

        # 检查每个组合
        best_hits = 0
        for combo in combinations:
            hits = sum(1 for c, s in zip(combo, sim_result) if c == s)  # noqa: B905
            if hits > best_hits:
                best_hits = hits

        if best_hits == 14:
            hit14_count += 1
        if best_hits >= 13:
            hit13_count += 1
        if best_hits >= 12:
            hit12_count += 1

        # 任九：检查最佳组合中有多少命中（从14场中取9场看）
        # 简化：如果14场中命中最多的组合，其命中>=9的概率
        if best_hits / 14 * 9 >= 9:
            rx9_count += 1
        elif best_hits >= 9:  # 如果至少命中9场任一场次
            rx9_count += 1

    return {
        "hit14_prob": hit14_count / n_simulations,
        "hit13_prob": hit13_count / n_simulations,
        "hit12_prob": hit12_count / n_simulations,
        "rx9_prob": rx9_count / n_simulations,
        "expected_hits": 0.0,  # filled below
        "n_simulations": n_simulations,
        "n_combinations": n_combos,
    }


def estimate_expected_hits(
    matches: list[PoolMatch],
    combination: tuple[str, ...],
) -> float:
    """估计单个组合的期望命中场次。"""
    total = 0.0
    for m, sel in zip(matches, combination):  # noqa: B905
        prob_map = {"3": m.prob_home, "1": m.prob_draw, "0": m.prob_away}
        total += prob_map.get(sel, 0.0)
    return total


# ---------------------------------------------------------------------------
# 完整分析 pipeline
# ---------------------------------------------------------------------------


def analyze_pool(
    matches: list[PoolMatch],
    budget: int = 256,
    unit_cost: int = 2,
    strategy: str = "balanced",
    n_mc_simulations: int = 10000,
    period_id: str = "",
) -> PoolAnalysis:
    """完整的14场/任九分析 pipeline。

    1. 胆拖防守分类
    2. 计算冷门指数
    3. 胆拖优化组合
    4. 蒙特卡洛模拟
    5. 任九选项
    6. 生成分析报告
    """
    from datetime import datetime

    if len(matches) < 2:
        raise ValueError(f"至少需要2场比赛，当前{len(matches)}场")

    # 1. 计算冷门指数
    for m in matches:
        m.cold_gate_index = compute_cold_gate_index(m)

    # 2. 胆拖防守分类
    classified = classify_matches(matches)

    # 3. 胆拖优化
    combos, stats = dan_tuo_optimize(
        classified, budget=budget, unit_cost=unit_cost, strategy=strategy
    )

    # 4. 蒙特卡洛模拟
    mc_results = monte_carlo_simulate(classified, combos, n_simulations=n_mc_simulations)

    # 5. 任九选项
    rx9_matches, rx9_indices = choose_rx9(classified)

    # 6. 生成组合结果
    full_results = []
    for combo in combos:
        cold_coverage = sum(
            1
            for i, (c, m) in enumerate(zip(combo, classified))  # noqa: B905
            if m.classification == "defense" and c != m.max_prob_option
        )
        defense_total = stats["defense_count"]
        full_results.append(
            CombinationResult(
                selections=list(combo),
                cost=unit_cost,
                dan_count=stats["dan_count"],
                tuo_count=stats["tuo_count"],
                defense_count=defense_total,
                cold_gate_coverage=cold_coverage / defense_total if defense_total > 0 else 0.0,
                estimated_hit_prob=estimate_expected_hits(classified, combo) / 14,
            )
        )

    # 任九组合（在9场中选中的）
    rx9_combos_raw, rx9_stats = dan_tuo_optimize(
        rx9_matches, budget=min(budget, 128), unit_cost=unit_cost, strategy=strategy
    )
    rx9_results = []
    for combo in rx9_combos_raw:
        rx9_results.append(
            CombinationResult(
                selections=list(combo),
                cost=unit_cost,
                estimated_hit_prob=estimate_expected_hits(rx9_matches, combo) / 9,
            )
        )

    # 7. 组装报告
    dan_indices = [i for i, m in enumerate(classified) if m.classification == "dan"]
    tuo_indices = [i for i, m in enumerate(classified) if m.classification == "tuo"]
    defense_indices = [i for i, m in enumerate(classified) if m.classification == "defense"]

    analysis = PoolAnalysis(
        period_id=period_id,
        matches=classified,
        dan_matches=dan_indices,
        tuo_matches=tuo_indices,
        defense_matches=defense_indices,
        full_combinations=full_results,
        rx9_combinations=rx9_results,
        mc_hit14_prob=mc_results["hit14_prob"],
        mc_hit13_prob=mc_results["hit13_prob"],
        mc_rx9_prob=mc_results["rx9_prob"],
        mc_total_cost=stats["total_cost"],
        mc_combinations_used=stats["actual_combos"],
        cold_gate_coverage=sum(r.cold_gate_coverage for r in full_results) / len(full_results)
        if full_results
        else 0.0,
        max_single_exposure=unit_cost,  # 简化：单注最大暴露
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )

    # 警告
    if stats["total_cost"] > budget:
        analysis.warnings.append(f"组合总成本 {stats['total_cost']} 元超出预算 {budget} 元")
    if len(defense_indices) > 5:
        analysis.warnings.append(f"防守场次过多 ({len(defense_indices)}场)，冷门风险较高")
    if analysis.mc_hit14_prob < 0.001:
        analysis.warnings.append("命中14场概率极低 (<0.1%)，建议增加预算或调整策略")

    return analysis


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def build_matches_from_predictions(
    predictions: list[dict[str, Any]],
) -> list[PoolMatch]:
    """从模型预测数据构建 PoolMatch 列表。

    输入格式：每个 dict 包含 match_id, home_team, away_team, league,
    prob_home, prob_draw, prob_away 等字段。
    """
    matches = []
    for p in predictions:
        m = PoolMatch(
            match_id=p.get("match_id"),
            home_team=p.get("home_team", ""),
            away_team=p.get("away_team", ""),
            league=p.get("league", ""),
            match_date=p.get("match_date", ""),
            prob_home=float(p.get("prob_home", 0.33)),
            prob_draw=float(p.get("prob_draw", 0.34)),
            prob_away=float(p.get("prob_away", 0.33)),
            market_odds_home=p.get("market_odds_home"),
            market_odds_draw=p.get("market_odds_draw"),
            market_odds_away=p.get("market_odds_away"),
            uncertainty=float(p.get("uncertainty", 0.5)),
            data_quality=float(p.get("data_quality", 0.0)),
        )
        matches.append(m)
    return matches


def pool_analysis_to_dict(analysis: PoolAnalysis) -> dict[str, Any]:
    """将 PoolAnalysis 序列化为 API 响应格式。"""
    return {
        "period_id": analysis.period_id,
        "matches": [
            {
                "index": i,
                "match_id": m.match_id,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "league": m.league,
                "match_date": m.match_date,
                "prob_home": round(m.prob_home, 4),
                "prob_draw": round(m.prob_draw, 4),
                "prob_away": round(m.prob_away, 4),
                "max_prob_option": m.max_prob_option,
                "max_prob": round(m.max_prob, 4),
                "cold_gate_index": round(m.cold_gate_index, 4),
                "uncertainty": round(m.uncertainty, 4),
                "data_quality": round(m.data_quality, 4),
                "classification": m.classification,
                "entropy": round(m.entropy, 4),
            }
            for i, m in enumerate(analysis.matches)
        ],
        "classification": {
            "dan": [
                analysis.matches[i].home_team + " vs " + analysis.matches[i].away_team
                for i in analysis.dan_matches
            ],
            "tuo": [
                analysis.matches[i].home_team + " vs " + analysis.matches[i].away_team
                for i in analysis.tuo_matches
            ],
            "defense": [
                analysis.matches[i].home_team + " vs " + analysis.matches[i].away_team
                for i in analysis.defense_matches
            ],
        },
        "full_combinations": {
            "count": len(analysis.full_combinations),
            "total_cost": len(analysis.full_combinations) * 2,
            "combinations": [
                {
                    "selections": c.selections,
                    "estimated_hit_prob": round(c.estimated_hit_prob, 4),
                    "cold_gate_coverage": round(c.cold_gate_coverage, 4),
                }
                for c in analysis.full_combinations[:50]  # 最多返回50个组合
            ],
        },
        "rx9": {
            "selected_matches": [
                analysis.matches[i].home_team + " vs " + analysis.matches[i].away_team
                for i in range(min(9, len(analysis.matches)))
            ],
            "combinations_count": len(analysis.rx9_combinations),
            "total_cost": len(analysis.rx9_combinations) * 2,
        },
        "monte_carlo": {
            "hit14_prob": round(analysis.mc_hit14_prob, 6),
            "hit13_prob": round(analysis.mc_hit13_prob, 6),
            "rx9_prob": round(analysis.mc_rx9_prob, 6),
            "simulations": 10000,
        },
        "warnings": analysis.warnings,
        "generated_at": analysis.generated_at,
    }
