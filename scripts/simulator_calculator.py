"""Simulator calculation engine — pure combinatorial math, no DB dependency.

Covers:
- Pass type registry (single / M串1 / M串N, 40+ types)
- Combinatorial decomposition of M matches into N bet combos
- Cost, max prize, bet count calculations
"""

from __future__ import annotations

from itertools import combinations, product
from math import comb

UNIT_STAKE = 2.0
MAX_MULTIPLE = 50
MAX_TICKET_COST = 20_000.0


def payout_cap(match_count: int) -> float:
    """Return the statutory per-bet prize ceiling for a concrete combination."""
    if match_count <= 1:
        return 100_000.0
    if match_count <= 3:
        return 200_000.0
    if match_count <= 5:
        return 500_000.0
    return 1_000_000.0


# ---- Play-type max matches per ticket ----

PLAY_TYPE_MAX_MATCHES: dict[str, int] = {
    "spf": 8,
    "rqspf": 8,
    "zjq": 6,
    "bf": 4,
    "bqc": 4,
    "hhgg": 8,  # mixed parlay — limited by the strictest play type among selected
}

# ---- Play-type display names ----

PLAY_TYPE_LABELS: dict[str, str] = {
    "spf": "胜平负",
    "rqspf": "让球胜平负",
    "zjq": "总进球数",
    "bf": "比分",
    "bqc": "半全场",
    "hhgg": "混合过关",
}

# ---- Pass type registry ----
# Each entry: list of (n, k) tuples — from n matches, pick k for each combination.
# bet_count = sum(C(n, k) for each spec)
# For 'single': special-cased in code.
# For 'Mx1': choose every M-match subset from the selected matches.

PASS_TYPE_REGISTRY: dict[str, list[tuple[int, int]]] = {
    # M串1: choose every M-match subset from the selected matches.
    "single": [(1, 1)],  # special: each match is its own independent bet
    "2x1": [(2, 2)],
    "3x1": [(3, 3)],
    "4x1": [(4, 4)],
    "5x1": [(5, 5)],
    "6x1": [(6, 6)],
    "7x1": [(7, 7)],
    "8x1": [(8, 8)],
    # ---- 3-match M串N ----
    "3x3": [(3, 2)],  # C(3,2) = 3
    "3x4": [(3, 2), (3, 3)],  # 3 + 1 = 4
    # ---- 4-match M串N ----
    "4x4": [(4, 3)],  # C(4,3) = 4
    "4x5": [(4, 3), (4, 4)],  # 4 + 1 = 5
    "4x6": [(4, 2)],  # C(4,2) = 6
    "4x11": [(4, 2), (4, 3), (4, 4)],  # 6 + 4 + 1 = 11
    # ---- 5-match M串N ----
    "5x5": [(5, 4)],  # C(5,4) = 5
    "5x6": [(5, 4), (5, 5)],  # 5 + 1 = 6
    "5x10": [(5, 2)],  # C(5,2) = 10
    "5x16": [(5, 3), (5, 4), (5, 5)],  # 10 + 5 + 1 = 16
    "5x20": [(5, 2), (5, 3)],  # 10 + 10 = 20
    "5x26": [(5, 2), (5, 3), (5, 4), (5, 5)],  # 10 + 10 + 5 + 1 = 26
    # ---- 6-match M串N ----
    "6x6": [(6, 5)],  # C(6,5) = 6
    "6x7": [(6, 5), (6, 6)],  # 6 + 1 = 7
    "6x15": [(6, 2)],  # C(6,2) = 15
    "6x20": [(6, 3)],  # C(6,3) = 20
    "6x22": [(6, 4), (6, 5), (6, 6)],  # 15 + 6 + 1 = 22
    "6x35": [(6, 2), (6, 3)],  # 15 + 20 = 35
    "6x42": [(6, 3), (6, 4), (6, 5), (6, 6)],  # 20 + 15 + 6 + 1 = 42
    "6x50": [(6, 2), (6, 3), (6, 4)],  # 15 + 20 + 15 = 50
    "6x57": [(6, 2), (6, 3), (6, 4), (6, 5), (6, 6)],  # 15 + 20 + 15 + 6 + 1 = 57
    # ---- 7-match M串N ----
    "7x7": [(7, 6)],  # C(7,6) = 7
    "7x8": [(7, 6), (7, 7)],  # 7 + 1 = 8
    "7x21": [(7, 5)],  # C(7,5) = 21
    "7x35": [(7, 4)],  # C(7,4) = 35
    "7x120": [
        (7, 2),
        (7, 3),
        (7, 4),
        (7, 5),
        (7, 6),
        (7, 7),
    ],  # 21+35+35+21+7+1 = 120
    # ---- 8-match M串N ----
    "8x8": [(8, 7)],  # C(8,7) = 8
    "8x9": [(8, 7), (8, 8)],  # 8 + 1 = 9
    "8x28": [(8, 6)],  # C(8,6) = 28
    "8x56": [(8, 5)],  # C(8,5) = 56
    "8x70": [(8, 4)],  # C(8,4) = 70
    "8x247": [
        (8, 2),
        (8, 3),
        (8, 4),
        (8, 5),
        (8, 6),
        (8, 7),
        (8, 8),
    ],  # 28+56+70+56+28+8+1 = 247
}

# Max matches allowed per pass type (the M in M串N must match exactly)
PASS_TYPE_MAX_MATCHES: dict[str, int] = {}
for _pt, _specs in PASS_TYPE_REGISTRY.items():
    if _pt == "single":
        PASS_TYPE_MAX_MATCHES[_pt] = 10  # single can have up to 10 matches
    else:
        # For M串N types, the M must match
        PASS_TYPE_MAX_MATCHES[_pt] = max(s[0] for s in _specs)


def get_pass_type_info(pass_type: str) -> dict:
    """Return bet_count, combo_specs, and max_matches for a pass type.

    Returns:
        {"pass_type": str, "bet_count": int, "combo_specs": list[(n,k)], "max_matches": int}
    """
    if pass_type not in PASS_TYPE_REGISTRY:
        raise ValueError(f"Unknown pass_type: {pass_type}")
    specs = PASS_TYPE_REGISTRY[pass_type]
    bet_count = sum(comb(n, k) for n, k in specs)
    return {
        "pass_type": pass_type,
        "bet_count": bet_count,
        "combo_specs": specs,
        "max_matches": PASS_TYPE_MAX_MATCHES.get(pass_type, 8),
    }


def parse_pass_types(pass_type: str | list[str]) -> list[str]:
    """Normalize the ticket's multi-select pass labels."""
    values = pass_type if isinstance(pass_type, list) else str(pass_type).split(",")
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result or ["single"]


def calculate_multi_all(items: list[dict], pass_types: str | list[str], multiple: int = 1) -> dict:
    """Aggregate independently selected pass labels into one ticket.

    Example: 3 matches + ``single,2x1`` => 3 + C(3,2) = 6 bets.
    """
    types = parse_pass_types(pass_types)
    results = [calculate_all(items, value, multiple) for value in types]
    result = {
        **results[0],
        "pass_type": ",".join(result["pass_type"] for result in results),
        "pass_types": types,
        "bet_count": sum(result["bet_count"] for result in results),
        "total_cost": round(sum(result["total_cost"] for result in results), 2),
        "max_prize": round(sum(result["max_prize"] for result in results), 2),
        "combinations": [combo for result in results for combo in result["combinations"]],
    }
    if result["total_cost"] > MAX_TICKET_COST:
        raise ValueError(f"单票金额不得超过20000元，当前为{result['total_cost']:.2f}元")
    return result


def _group_items_by_match(items: list[dict]) -> list[list[dict]]:
    grouped: dict[object, list[dict]] = {}
    for index, item in enumerate(items):
        match_id = item.get("match_id")
        key = match_id if match_id is not None else f"__missing_{index}"
        grouped.setdefault(key, []).append(item)
    return list(grouped.values())


def get_available_pass_types(match_count: int | list[dict]) -> list[str]:
    """Return all pass types that are valid for the given number of matches.

    Includes straight M串1 options where M is not greater than current match_count.
    Compound M串N types are only exposed for their exact M-match ticket.
    """
    if isinstance(match_count, list):
        items = match_count
        effective_match_count = len(_group_items_by_match(items))
    else:
        items = None
        effective_match_count = match_count
    available: list[str] = []
    if effective_match_count >= 1:
        if items is None or any(item.get("is_single_allowed", True) for item in items):
            available.append("single")
    pass_allowed = items is None or all(item.get("is_pass_allowed", True) for item in items)
    strictest_limit = min(
        (PLAY_TYPE_MAX_MATCHES.get(item.get("play_type", "spf"), 8) for item in (items or [])),
        default=8,
    )
    for pt, specs in PASS_TYPE_REGISTRY.items():
        if pt == "single":
            continue
        if not pass_allowed:
            continue
        if pt.endswith("x1"):
            required = int(pt.split("x")[0])
            if required <= effective_match_count and required <= strictest_limit:
                available.append(pt)
            continue
        for n, _k in specs:
            if n == effective_match_count and n <= strictest_limit:
                available.append(pt)
                break
    return available


def calculate_bet_combinations(matches: list[dict], pass_type: str) -> list[list[dict]]:
    """Decompose M matches into N bet combinations based on pass_type.

    - 'single': each match is its own 1-match combo → returns M combos
    - 'Mx1': every M-match subset from selected matches
    - M串N: generates k-combinations per spec, e.g. 4x11 → 11 combos

    Each match dict must have at least: match_id, option_code, sp_value
    """
    if pass_type not in PASS_TYPE_REGISTRY:
        raise ValueError(f"Unknown pass_type: {pass_type}")

    match_groups = _group_items_by_match(matches)
    n_matches = len(match_groups)
    specs = PASS_TYPE_REGISTRY[pass_type]

    # Separate dan (banker) matches — they appear in ALL combos
    dan_groups = [group for group in match_groups if any(item.get("is_dan") for item in group)]
    normal_groups = [
        group for group in match_groups if not any(item.get("is_dan") for item in group)
    ]
    n_dan = len(dan_groups)
    n_normal = len(normal_groups)

    def expand(groups: list[list[dict]]) -> list[list[dict]]:
        return [list(selection) for selection in product(*groups)] if groups else [[]]

    if pass_type == "single":
        # Each match is its own independent bet (1x1)
        return [
            [item]
            for group in match_groups
            for item in group
            if item.get("is_single_allowed", True)
        ]

    if pass_type.endswith("x1") and pass_type != "single":
        # M串1: choose every M-match combination from the current selections.
        k = int(pass_type.split("x")[0])
        if n_matches < k:
            raise ValueError(
                f"Pass type '{pass_type}' requires at least {k} matches, got {n_matches}"
            )
        k_effective = k - n_dan
        if k_effective < 0:
            raise ValueError(
                f"Too many dan matches ({n_dan}) for pass type '{pass_type}': "
                f"at most {k} matches can be in a combo"
            )
        if k_effective == 0:
            return expand(dan_groups)
        return [
            concrete
            for combo_indices in combinations(range(n_normal), k_effective)
            for concrete in expand(dan_groups + [normal_groups[i] for i in combo_indices])
        ]

    # M串N: generate k-combinations per spec
    bet_combos: list[list[dict]] = []
    for n, k in specs:
        if n != n_matches:
            raise ValueError(f"Pass spec ({n},{k}) requires {n} matches, got {n_matches}")
        # Adjust k for dan matches: dan matches already count toward the k total
        k_effective = k - n_dan
        if k_effective < 0:
            raise ValueError(
                f"Too many dan matches ({n_dan}) for spec ({n},{k}): "
                f"at most {k} matches can be in a combo"
            )
        if k_effective == 0:
            # All required matches are dan → one combo of just dan matches
            bet_combos.extend(expand(dan_groups))
        else:
            for combo_indices in combinations(range(n_normal), k_effective):
                groups = dan_groups + [normal_groups[i] for i in combo_indices]
                bet_combos.extend(expand(groups))

    return bet_combos


def calculate_max_prize(combinations_result: list[list[dict]], multiple: int = 1) -> float:
    """Calculate max potential prize across all combinations.

    For each combination: product of all SP values × 2 yuan base.
    Sum all combos' max prizes, then multiply by the ticket multiple.

    Uses banker's rounding (四舍六入五成双) to 2 decimal places.
    """
    total = 0.0
    for combo in combinations_result:
        combo_sp = 1.0
        for item in combo:
            combo_sp *= float(item["sp_value"])
        total += min(combo_sp * UNIT_STAKE, payout_cap(len(combo)))
    return round(total * multiple, 2)


def calculate_winning_prize(
    items: list[dict], pass_types: str | list[str], multiple: int = 1
) -> float:
    """Calculate the actual prize from settled selections.

    Each item must include ``is_won``. Selections from the same match are
    alternatives, so only one can enter a concrete combination. Multiple pass
    labels are settled independently and their winning prizes are added.
    """
    total = 0.0
    for pass_type in parse_pass_types(pass_types):
        for combo in calculate_bet_combinations(items, pass_type):
            if not combo or not all(bool(item.get("is_won")) for item in combo):
                continue
            combo_sp = 1.0
            for item in combo:
                combo_sp *= float(item["sp_value"])
            total += min(combo_sp * UNIT_STAKE, payout_cap(len(combo))) * multiple
    return round(total, 2)


def calculate_cost(match_count: int, pass_type: str, multiple: int = 1) -> float:
    """Total cost = bet_count × 2 yuan base × multiple."""
    info = get_pass_type_info(pass_type)
    # For 'single', bet_count == number of matches (each match is a separate bet)
    if pass_type == "single":
        bet_count = match_count
    elif pass_type.endswith("x1"):
        required = int(pass_type.split("x")[0])
        if match_count < required:
            raise ValueError(
                f"Pass type '{pass_type}' requires at least {required} matches, got {match_count}"
            )
        bet_count = comb(match_count, required)
    else:
        bet_count = info["bet_count"]
    return round(bet_count * UNIT_STAKE * multiple, 2)


def calculate_all(
    items: list[dict],
    pass_type: str,
    multiple: int = 1,
) -> dict:
    """Run full calculation: bet count, cost, max prize, and all combinations.

    Args:
        items: list of bet item dicts with {match_id, play_type, option_code,
               option_name, sp_value, handicap, is_dan}
        pass_type: e.g. 'single', '2x1', '4x11'
        multiple: multiplier (1-50)

    Returns:
        {pass_type, multiple, bet_count, total_cost, max_prize, match_count,
         combinations: [{items, combo_sp, max_prize}]}
    """
    if not 1 <= multiple <= MAX_MULTIPLE:
        raise ValueError("倍数必须在1到50之间")

    match_count = len(_group_items_by_match(items))

    # Generate combinations
    combos = calculate_bet_combinations(items, pass_type)

    # Cost
    bet_count = len(combos)
    total_cost = round(bet_count * UNIT_STAKE * multiple, 2)
    if total_cost > MAX_TICKET_COST:
        raise ValueError(f"单票金额不得超过20000元，当前为{total_cost:.2f}元")
    max_prize = calculate_max_prize(combos, multiple)

    # Format combinations for response
    combo_details = []
    for combo in combos:
        combo_sp = 1.0
        for item in combo:
            combo_sp *= float(item["sp_value"])
        combo_prize = round(min(combo_sp * UNIT_STAKE, payout_cap(len(combo))) * multiple, 2)
        combo_details.append(
            {
                "items": [
                    {
                        "match_id": item["match_id"],
                        "option_code": item["option_code"],
                        "sp_value": item["sp_value"],
                    }
                    for item in combo
                ],
                "combo_sp": round(combo_sp, 4),
                "max_prize": combo_prize,
            }
        )

    return {
        "pass_type": pass_type,
        "multiple": multiple,
        "bet_count": bet_count,
        "total_cost": total_cost,
        "max_prize": max_prize,
        "match_count": match_count,
        "selection_count": len(items),
        "combinations": combo_details,
    }


def validate_items(items: list[dict], pass_type: str) -> list[str]:
    """Validate bet items against play-type rules. Returns list of error messages."""
    errors: list[str] = []

    if not items:
        errors.append("至少需要选择1场比赛")
        return errors

    match_ids = [item.get("match_id") for item in items]
    if any(match_id is None for match_id in match_ids):
        errors.append("每个投注项必须包含官方比赛编号")
    selection_keys = [
        (item.get("match_id"), item.get("play_type"), item.get("option_code")) for item in items
    ]
    if len(selection_keys) != len(set(selection_keys)):
        errors.append("同一场比赛的同一投注选项不能重复添加")
    match_count = len(set(match_ids))

    # Check pass type exists
    if pass_type not in PASS_TYPE_REGISTRY:
        errors.append(f"不支持的过关方式: {pass_type}")
        return errors

    if pass_type == "single":
        if not any(item.get("is_single_allowed", True) for item in items):
            errors.append(f"比赛 {items[0].get('match_id')} 的该玩法不支持单关")
    else:
        for item in items:
            if item.get("is_pass_allowed") is False:
                errors.append(f"比赛 {item.get('match_id')} 的该玩法仅支持单场")

    # Check match count matches pass type
    info = get_pass_type_info(pass_type)
    if pass_type != "single":
        if pass_type.endswith("x1"):
            n_have = int(pass_type.split("x")[0])
            if match_count < n_have:
                errors.append(
                    f"过关方式 '{pass_type}' 至少需要 {n_have} 场比赛，当前选择了 {match_count} 场"
                )
        else:
            for n_have, _k in info["combo_specs"]:
                if match_count != n_have:
                    errors.append(
                        f"过关方式 '{pass_type}' 需要恰好 {n_have} 场比赛，当前选择了 {match_count} 场"
                    )
                    break

    # A straight pass (Mx1) limits each generated combination to M matches;
    # selecting more matches is valid and expands into C(selected, M) bets.
    # Compound M串N types still require their exact M-match ticket shape.
    play_types: set[str] = {item.get("play_type", "spf") for item in items}
    strictest_play = min(play_types, key=lambda pt: PLAY_TYPE_MAX_MATCHES.get(pt, 8))
    strictest_max = PLAY_TYPE_MAX_MATCHES.get(strictest_play, 8)
    required_pass_matches = (
        int(pass_type.split("x")[0])
        if pass_type.endswith("x1") and pass_type != "single"
        else match_count
    )
    if required_pass_matches > strictest_max:
        errors.append(
            f"玩法 '{PLAY_TYPE_LABELS.get(strictest_play, strictest_play)}' 每个组合最多 {strictest_max} 场，当前过关需要 {required_pass_matches} 场"
        )

    # Validate sp_value
    for i, item in enumerate(items):
        sp = item.get("sp_value", 0)
        if not sp or float(sp) <= 0:
            errors.append(f"第 {i + 1} 场比赛赔率无效")

    # Validate multiple range
    return errors


# ---- Self-test (run with: python -m scripts.simulator_calculator) ----

if __name__ == "__main__":
    print("=== Simulator Calculator Self-Test ===\n")

    # Test get_pass_type_info
    for pt in ["single", "2x1", "4x11", "6x57", "8x247"]:
        info = get_pass_type_info(pt)
        print(f"{pt}: bet_count={info['bet_count']}, max_matches={info['max_matches']}")

    # Test calculate_bet_combinations for 4x11
    matches = [
        {"match_id": 1, "option_code": "3", "sp_value": 2.10, "is_dan": False},
        {"match_id": 2, "option_code": "1", "sp_value": 3.50, "is_dan": False},
        {"match_id": 3, "option_code": "0", "sp_value": 3.20, "is_dan": False},
        {"match_id": 4, "option_code": "3", "sp_value": 1.80, "is_dan": False},
    ]
    combos = calculate_bet_combinations(matches, "4x11")
    print(f"\n4x11: {len(combos)} combinations (expected 11)")
    assert len(combos) == 11, f"Expected 11, got {len(combos)}"

    # Test calculate_all
    result = calculate_all(matches, "4x11", multiple=1)
    print(
        f"  bet_count={result['bet_count']}, cost={result['total_cost']}, max_prize={result['max_prize']}"
    )
    assert result["bet_count"] == 11
    assert result["total_cost"] == 22.0  # 11 × 2 × 1

    # Test single
    result_single = calculate_all(matches, "single", multiple=5)
    print(
        f"\nsingle (4 matches, 5x): bet_count={result_single['bet_count']}, cost={result_single['total_cost']}"
    )
    assert result_single["bet_count"] == 4
    assert result_single["total_cost"] == 40.0  # 4 × 2 × 5

    # Test 3x3
    matches_3 = matches[:3]
    result_3x3 = calculate_all(matches_3, "3x3", multiple=1)
    print(
        f"\n3x3: bet_count={result_3x3['bet_count']}, cost={result_3x3['total_cost']}, combos={len(result_3x3['combinations'])}"
    )
    assert result_3x3["bet_count"] == 3  # C(3,2) = 3
    assert len(result_3x3["combinations"]) == 3

    # Test get_available_pass_types
    for mc in [2, 3, 4, 6, 8]:
        available = get_available_pass_types(mc)
        print(f"\nAvailable pass types for {mc} matches: {available}")

    # Test dan (banker) logic
    matches_with_dan = [
        {"match_id": 1, "option_code": "3", "sp_value": 2.10, "is_dan": True},
        {"match_id": 2, "option_code": "1", "sp_value": 3.50, "is_dan": False},
        {"match_id": 3, "option_code": "0", "sp_value": 3.20, "is_dan": False},
    ]
    combos_dan = calculate_bet_combinations(matches_with_dan, "3x3")
    print(f"\n3x3 with 1 dan: {len(combos_dan)} combos")
    for c in combos_dan:
        dan_count = sum(1 for m in c if m.get("is_dan"))
        print(
            f"  combo: {[(m['match_id'], 'dan' if m.get('is_dan') else 'normal') for m in c]}, dan_count={dan_count}"
        )
        assert dan_count == 1, "Dan match should appear in every combo"

    # Test max prize calculation
    prize = calculate_max_prize(combos_dan, multiple=1)
    print(f"  max_prize={prize}")

    # Test validation
    errors = validate_items([], "2x1")
    print(f"\nValidation (empty items): {errors}")
    assert len(errors) > 0

    errors2 = validate_items(matches[:3], "4x1")
    print(f"Validation (3 matches for 4x1): {errors2}")
    assert len(errors2) > 0

    print("\n=== All tests passed! ===")
