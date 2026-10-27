import math
from itertools import product

import pytest

from scripts.pool_combination_optimizer import (
    PoolMatch,
    analyze_pool,
    pool_analysis_to_dict,
    portfolio_probabilities,
    top_combinations,
)


def matches(n=14):
    return [
        PoolMatch(
            match_id=i + 100, match_order=i + 1, prob_home=0.4, prob_draw=0.35, prob_away=0.25
        )
        for i in range(n)
    ]


def test_exact_probabilities_deduplicate_overlapping_prize_events():
    ms = matches(3)
    tickets = [("3", "3", "3"), ("3", "3", "1"), ("3", "3", "3")]
    result = portfolio_probabilities(ms, tickets, one_miss=True)
    expected_all = expected_one = 0
    probs = {"3": 0.4, "1": 0.35, "0": 0.25}
    for outcome in product("310", repeat=3):
        p = math.prod(probs[o] for o in outcome)
        distance = min(sum(a != b for a, b in zip(outcome, t, strict=True)) for t in tickets)
        if distance == 0:
            expected_all += p
        if distance <= 1:
            expected_one += p
    assert result["all_correct"] == pytest.approx(expected_all)
    assert result["at_least_one_less"] == pytest.approx(expected_one)


def test_top_k_matches_exhaustive_joint_probability_order():
    ms = matches(4)
    ms[0].prob_home, ms[0].prob_draw, ms[0].prob_away = 0.51, 0.48, 0.01
    choices = [list("310") for _ in ms]
    actual = top_combinations(ms, choices, 11)

    def score(t):
        return math.prod(
            dict(zip("310", [m.prob_home, m.prob_draw, m.prob_away], strict=True))[o]
            for m, o in zip(ms, t, strict=True)
        )

    expected = sorted(
        product(*choices), key=lambda t: (-score(t), tuple("310".index(o) for o in t))
    )[:11]
    assert actual == expected


def test_rx9_keeps_selected_identity_and_uses_full_budget():
    ms = matches()
    for i in range(5, 14):
        ms[i].prob_home, ms[i].prob_draw, ms[i].prob_away = 0.5, 0.3, 0.2
    result = pool_analysis_to_dict(analyze_pool(ms, budget=256))
    assert [m["match_order"] for m in result["rx9"]["selected_matches"]] == list(range(6, 15))
    assert result["rx9"]["total_cost"] == 256
    assert result["rx9"]["combinations_count"] == 128
    assert result["classification"]["dan"] == []
    assert result["probability_method"] == "independent-exact-v1"
    assert "monte_carlo" not in result


def test_missing_models_do_not_block_rx9_or_invent_full_probability():
    ms = matches()
    for m in ms[10:]:
        m.prob_home = m.prob_draw = m.prob_away = None
    result = pool_analysis_to_dict(analyze_pool(ms))
    assert result["sf14_status"] == "missing_predictions"
    assert result["rx9_status"] == "ready"
    assert result["probabilities"]["hit14_prob"] is None
    assert len(result["rx9"]["selected_matches"]) == 9
    assert len(result["missing_inputs"]) == 4


@pytest.mark.parametrize("budget", [0, -2, 3, 2.5, True, 10002])
def test_invalid_budgets_rejected(budget):
    with pytest.raises(ValueError, match="预算"):
        analyze_pool(matches(), budget=budget)


def test_rare_probability_is_not_rounded_to_zero_and_snapshot_keeps_all_tickets():
    result = pool_analysis_to_dict(analyze_pool(matches(), budget=10000, strategy="aggressive"))
    assert result["full_combinations"]["count"] == 5000
    assert len(result["full_combinations"]["combinations"]) == 5000
    assert result["full_combinations"]["combinations"][0]["all_correct_prob"] == pytest.approx(
        0.4**14
    )
    assert result["full_combinations"]["combinations"][0]["expected_hits"] == pytest.approx(
        14 * 0.4
    )


def test_pin_exclude_validation_and_no_mutation():
    ms = matches()
    result = pool_analysis_to_dict(analyze_pool(ms, pinned_orders=[14], excluded_orders=[1]))
    orders = [m["match_order"] for m in result["rx9"]["selected_matches"]]
    assert 14 in orders and 1 not in orders
    assert all(m.classification == "normal" for m in ms)
    with pytest.raises(ValueError, match="固定"):
        analyze_pool(ms, pinned_orders=list(range(1, 11)))
    with pytest.raises(ValueError):
        analyze_pool(ms, pinned_orders=[1], excluded_orders=[1])


def test_rounding_normalized_for_calculation_but_raw_input_retained_and_zero_valid():
    ms = matches()
    for m in ms:
        m.prob_home, m.prob_draw, m.prob_away = 0.499, 0.5, 0
    result = pool_analysis_to_dict(analyze_pool(ms, budget=2))
    assert result["matches"][0]["raw_probability_sum"] == 0.999
    assert result["matches"][0]["prob_home"] == 0.499
    assert result["full_combinations"]["combinations"][0]["all_correct_prob"] == pytest.approx(
        (0.5 / 0.999) ** 14
    )
    ms[0].prob_home = True
    assert pool_analysis_to_dict(analyze_pool(ms))["sf14_status"] == "missing_predictions"
