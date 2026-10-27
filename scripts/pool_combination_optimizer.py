"""Traditional pool portfolios: deterministic probabilities under independent matches.

The ranking is optimal only for all-correct probability within fixed per-match
choices; it does not optimize 13-hit coverage or establish real model accuracy.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scripts.business_time import business_now
from scripts.market_metric_validation import spf_probability_vector

OPTIONS = ("3", "1", "0")
METHOD = "independent-exact-v1"
ASSUMPTION = "按输入概率与场次独立假设计算；不代表真实命中率，也未处理比赛之间的相关性。"


@lru_cache(maxsize=1)
def pool_rules() -> dict[str, int]:
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs/pool_rules.yaml").read_text()
    )["football_pool"]
    unit = config["unit_cost"]
    if type(unit) is not int or unit != 2:
        raise ValueError("传统足彩单注金额配置必须为2元")
    return {
        "unit_cost": unit,
        "sf14": int(config["sf14"]["matches"]),
        "rx9": int(config["rx9"]["select_matches"]),
    }


def validate_budget(budget: int) -> None:
    if type(budget) is not int or not 2 <= budget <= 10000 or budget % pool_rules()["unit_cost"]:
        raise ValueError("预算须为2至10000元之间的偶数整数")


@dataclass
class PoolMatch:
    match_id: int | None = None
    match_order: int = 0
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    match_date: str = ""
    prob_home: float | None = None
    prob_draw: float | None = None
    prob_away: float | None = None
    market_odds_home: float | None = None
    market_odds_draw: float | None = None
    market_odds_away: float | None = None
    uncertainty: float | None = None
    data_quality: float | None = None
    is_derby: bool = False
    is_top_clash: bool = False
    classification: str = "normal"
    evidence: dict[str, Any] = field(default_factory=dict)
    missing_reason: str | None = None

    @property
    def vector(self) -> dict[str, float] | None:
        return spf_probability_vector(
            dict(zip(OPTIONS, (self.prob_home, self.prob_draw, self.prob_away), strict=True))
        )

    @property
    def normalized(self) -> dict[str, float]:
        vector = self.vector
        if vector is None:
            raise ValueError("完整概率向量无效")
        total = math.fsum(vector.values())
        return {o: p / total for o, p in vector.items()}

    @property
    def max_prob(self) -> float:
        return max(self.normalized.values())

    @property
    def max_prob_option(self) -> str:
        return max(OPTIONS, key=lambda o: self.normalized[o])

    @property
    def entropy(self) -> float:
        return -math.fsum(p * math.log2(p) for p in self.normalized.values() if p > 0)


def classify_matches(matches: list[PoolMatch], dan_threshold: float = 0.55) -> list[PoolMatch]:
    # No forced minimum of bankers, no invented upset or completeness score.
    return [
        replace(m, classification="dan" if m.max_prob >= dan_threshold else "tuo") for m in matches
    ]


def get_match_options(match: PoolMatch, strategy: str = "balanced") -> list[str]:
    ranked = sorted(OPTIONS, key=lambda o: -match.normalized[o])
    size = (
        1
        if strategy == "conservative" or match.classification == "dan"
        else (3 if strategy == "aggressive" else 2)
    )
    return ranked[:size]


def top_combinations(
    matches: list[PoolMatch], choices: list[list[str]], limit: int
) -> list[tuple[str, ...]]:
    """Best-first traversal of the monotonic product lattice; stable option ties."""
    if not matches or limit <= 0:
        return []
    vectors = [m.normalized for m in matches]
    ranked = [
        sorted(set(opts), key=lambda o: (-v[o], OPTIONS.index(o)))
        for opts, v in zip(choices, vectors, strict=True)
    ]

    def entry(indices):
        combo = tuple(opts[i] for opts, i in zip(ranked, indices, strict=True))
        p = math.prod(v[o] for v, o in zip(vectors, combo, strict=True))
        return (-p, tuple(OPTIONS.index(o) for o in combo), indices, combo)

    start = (0,) * len(matches)
    heap = [entry(start)]
    seen = {start}
    result: list[tuple[str, ...]] = []
    while heap and len(result) < limit:
        _, _, indices, combo = heapq.heappop(heap)
        result.append(combo)
        for dim in range(len(matches)):
            if indices[dim] + 1 >= len(ranked[dim]):
                continue
            neighbor = indices[:dim] + (indices[dim] + 1,) + indices[dim + 1 :]
            if neighbor not in seen:
                seen.add(neighbor)
                heapq.heappush(heap, entry(neighbor))
    return result


def portfolio_probabilities(
    matches: list[PoolMatch], combinations: list[tuple[str, ...]], *, one_miss: bool = False
) -> dict[str, float]:
    vectors = [m.normalized for m in matches]
    unique = set(combinations)
    if any(len(t) != len(matches) or any(o not in OPTIONS for o in t) for t in unique):
        raise ValueError("组合与场数或选项不一致")

    def probability(ticket):
        return math.prod(v[o] for v, o in zip(vectors, ticket, strict=True))

    full = math.fsum(probability(t) for t in sorted(unique))
    coverage = set(unique)
    if one_miss:
        for ticket in unique:
            for i in range(len(matches)):
                for option in OPTIONS:
                    if option != ticket[i]:
                        coverage.add(ticket[:i] + (option,) + ticket[i + 1 :])
    return {
        "all_correct": min(full, 1.0),
        "at_least_one_less": min(math.fsum(probability(t) for t in sorted(coverage)), 1.0)
        if one_miss
        else full,
    }


def choose_rx9(
    matches: list[PoolMatch],
    *,
    pinned_orders: list[int] | None = None,
    excluded_orders: list[int] | None = None,
) -> list[PoolMatch]:
    pins, excludes = set(pinned_orders or []), set(excluded_orders or [])
    valid_orders = {m.match_order for m in matches}
    if len(pins) > pool_rules()["rx9"] or pins & excludes or not pins <= valid_orders:
        raise ValueError("固定场次须有效、不超过9场，且不能同时排除")
    if not excludes <= set(range(1, 15)):
        raise ValueError("排除场序必须为1至14")
    eligible = [m for m in matches if m.match_order not in excludes]
    if len(eligible) < 9:
        return []
    ranked = sorted(
        (m for m in eligible if m.match_order not in pins),
        key=lambda m: (-m.max_prob, m.entropy, m.match_order),
    )
    selected = [m for m in eligible if m.match_order in pins] + ranked[: 9 - len(pins)]
    return sorted(selected, key=lambda m: m.match_order)


@dataclass
class PoolAnalysis:
    period_id: str
    matches: list[PoolMatch]
    budget: int
    strategy: str
    selected_rx9: list[PoolMatch]
    full_combinations: list[tuple[str, ...]]
    rx9_combinations: list[tuple[str, ...]]
    probabilities: dict[str, float | None]
    generated_at: str


def analyze_pool(
    matches: list[PoolMatch],
    budget: int = 256,
    strategy: str = "balanced",
    period_id: str = "",
    *,
    pinned_orders: list[int] | None = None,
    excluded_orders: list[int] | None = None,
) -> PoolAnalysis:
    validate_budget(budget)
    if strategy not in {"conservative", "balanced", "aggressive"}:
        raise ValueError("未知组合策略")
    if len(matches) > 14:
        raise ValueError("官方彩池最多14场")
    copied = [replace(m, match_order=m.match_order or i + 1) for i, m in enumerate(matches)]
    if len({m.match_order for m in copied}) != len(copied) or any(
        not 1 <= m.match_order <= 14 for m in copied
    ):
        raise ValueError("官方场序冲突")
    valid = classify_matches([m for m in copied if m.vector is not None and not m.missing_reason])
    by_order = {m.match_order: m for m in valid}
    copied = [by_order.get(m.match_order, m) for m in copied]
    rx9 = choose_rx9(valid, pinned_orders=pinned_orders, excluded_orders=excluded_orders)
    units = budget // pool_rules()["unit_cost"]
    full = (
        top_combinations(valid, [get_match_options(m, strategy) for m in valid], units)
        if len(valid) == 14
        else []
    )
    nine = (
        top_combinations(rx9, [get_match_options(m, strategy) for m in rx9], units) if rx9 else []
    )
    p14 = portfolio_probabilities(valid, full, one_miss=True) if full else None
    p9 = portfolio_probabilities(rx9, nine) if nine else None
    return PoolAnalysis(
        period_id,
        copied,
        budget,
        strategy,
        rx9,
        full,
        nine,
        {
            "hit14_prob": p14["all_correct"] if p14 else None,
            "hit13_or_more_prob": p14["at_least_one_less"] if p14 else None,
            "rx9_prob": p9["all_correct"] if p9 else None,
        },
        business_now().isoformat(),
    )


def pool_analysis_to_dict(analysis: PoolAnalysis) -> dict[str, Any]:
    matches = analysis.matches

    def describe(m):
        item = asdict(m)
        valid = m.vector is not None and not m.missing_reason
        item.update(
            available=valid,
            entropy=m.entropy if valid else None,
            max_prob=m.max_prob if valid else None,
            max_prob_option=m.max_prob_option if valid else None,
            raw_probability_sum=math.fsum(m.vector.values()) if valid else None,
            calculation_normalized=bool(valid and math.fsum(m.vector.values()) != 1.0),
        )
        return item

    def tickets(ms, combos):
        vectors = [m.normalized for m in ms]
        return [
            {
                "selections": list(t),
                "all_correct_prob": math.prod(v[o] for v, o in zip(vectors, t, strict=True)),
                "expected_hits": math.fsum(v[o] for v, o in zip(vectors, t, strict=True)),
            }
            for t in combos
        ]

    full = tickets(matches, analysis.full_combinations) if analysis.full_combinations else []
    nine = tickets(analysis.selected_rx9, analysis.rx9_combinations)
    return {
        "schema_version": "football-pool/v2",
        "calculation_version": METHOD,
        "probability_method": METHOD,
        "assumptions": [ASSUMPTION],
        "period_id": analysis.period_id,
        "parameters": {"budget": analysis.budget, "strategy": analysis.strategy},
        "unit_cost": pool_rules()["unit_cost"],
        "generated_at": analysis.generated_at,
        "matches": [describe(m) for m in matches],
        "classification": {
            c: [f"{m.home_team} vs {m.away_team}" for m in matches if m.classification == c]
            for c in ["dan", "tuo", "defense"]
        },
        "full_combinations": {
            "count": len(full),
            "total_cost": len(full) * pool_rules()["unit_cost"],
            "combinations": full,
        },
        "rx9": {
            "selected_matches": [describe(m) for m in analysis.selected_rx9],
            "combinations_count": len(nine),
            "total_cost": len(nine) * pool_rules()["unit_cost"],
            "combinations": nine,
            "selection_method": "max-probability-entropy-heuristic",
        },
        "probabilities": analysis.probabilities,
        "sf14_status": "ready" if full else "missing_predictions",
        "rx9_status": "ready" if nine else "missing_predictions",
        "missing_inputs": [
            {
                "match_order": m.match_order,
                "match_id": m.match_id,
                "reason": m.missing_reason or "缺少合格完整预测组",
            }
            for m in matches
            if m.vector is None or m.missing_reason
        ],
        "warnings": [
            ASSUMPTION,
            "两种玩法分别使用该预算，并列展示不代表同时购买。",
            "任九选场为启发式建议；胆仅表示单选，不保证获胜。",
        ],
    }
