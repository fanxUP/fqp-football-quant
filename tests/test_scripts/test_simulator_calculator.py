import pytest

from scripts.simulator_calculator import (
    calculate_all,
    calculate_bet_combinations,
    calculate_multi_all,
    calculate_winning_prize,
    get_available_pass_types,
    validate_items,
)


def _items(count: int) -> list[dict]:
    return [
        {
            "match_id": index + 1,
            "play_type": "spf",
            "option_code": "3",
            "sp_value": 2.0 + index,
            "is_dan": False,
        }
        for index in range(count)
    ]


def test_two_by_one_with_three_matches_is_three_pair_combinations():
    items = _items(3)

    assert validate_items(items, "2x1") == []

    combos = calculate_bet_combinations(items, "2x1")
    assert len(combos) == 3
    assert [sorted(item["match_id"] for item in combo) for combo in combos] == [
        [1, 2],
        [1, 3],
        [2, 3],
    ]

    result = calculate_all(items, "2x1", multiple=1)
    assert result["bet_count"] == 3
    assert result["total_cost"] == 6.0


def test_available_pass_types_include_lower_straight_passes():
    available = get_available_pass_types(3)

    assert "2x1" in available
    assert "3x1" in available


@pytest.mark.parametrize("play_type", ["bf", "bqc"])
def test_four_pass_allows_more_selected_matches_for_score_limited_plays(play_type):
    items = _items(5)
    for item in items:
        item["play_type"] = play_type
        item["is_pass_allowed"] = True

    assert validate_items(items, "4x1") == []
    result = calculate_all(items, "4x1", multiple=1)

    assert result["match_count"] == 5
    assert result["bet_count"] == 5
    assert result["total_cost"] == 10.0
    assert {tuple(sorted(item["match_id"] for item in combo)) for combo in calculate_bet_combinations(items, "4x1")} == {
        (1, 2, 3, 4), (1, 2, 3, 5), (1, 2, 4, 5), (1, 3, 4, 5), (2, 3, 4, 5)
    }


def test_single_requires_official_single_eligibility_when_present():
    item = _items(1)[0]
    item["is_single_allowed"] = False
    assert validate_items([item], "single") == ["比赛 1 的该玩法不支持单关"]


def test_multi_selected_pass_labels_are_added_not_replaced():
    result = calculate_multi_all(_items(3), ["single", "2x1"], multiple=1)
    assert result["pass_types"] == ["single", "2x1"]
    assert result["bet_count"] == 6
    assert result["total_cost"] == 12.0


def test_multiple_options_on_one_match_expand_as_alternative_bets():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 2.0, "is_dan": False},
        {"match_id": 1, "play_type": "rqspf", "option_code": "1", "sp_value": 3.0, "is_dan": False},
        {"match_id": 2, "play_type": "spf", "option_code": "0", "sp_value": 1.5, "is_dan": False},
    ]

    assert validate_items(items, "2x1") == []
    result = calculate_all(items, "2x1", multiple=1)

    assert result["match_count"] == 2
    assert result["selection_count"] == 3
    assert result["bet_count"] == 2
    assert result["total_cost"] == 4.0
    assert result["max_prize"] == 15.0


def test_single_only_option_cannot_enter_a_pass():
    items = _items(2)
    items[0]["is_pass_allowed"] = False

    assert validate_items(items, "2x1") == ["比赛 1 的该玩法仅支持单场"]


def test_settlement_pays_each_winning_subset_in_a_straight_pass():
    items = [
        {"match_id": 1, "option_code": "3", "sp_value": 2.0, "is_won": True},
        {"match_id": 2, "option_code": "1", "sp_value": 3.0, "is_won": True},
        {"match_id": 3, "option_code": "0", "sp_value": 4.0, "is_won": False},
    ]

    assert calculate_winning_prize(items, "2x1", multiple=1) == 12.0


def test_settlement_treats_same_match_options_as_alternatives():
    items = [
        {"match_id": 1, "option_code": "3", "sp_value": 2.0, "is_won": True},
        {"match_id": 1, "option_code": "1", "sp_value": 3.0, "is_won": False},
        {"match_id": 2, "option_code": "0", "sp_value": 4.0, "is_won": True},
    ]

    assert calculate_winning_prize(items, "2x1", multiple=2) == 32.0


def test_single_ticket_prize_is_capped_before_multiple():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 100_000, "is_won": True},
    ]

    result = calculate_all(items, "single", multiple=2)

    assert result["max_prize"] == 200_000.0
    assert calculate_winning_prize(items, "single", multiple=2) == 200_000.0


def test_two_match_ticket_prize_uses_two_to_three_match_cap():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 1_000, "is_won": True},
        {"match_id": 2, "play_type": "spf", "option_code": "3", "sp_value": 1_000, "is_won": True},
    ]

    result = calculate_all(items, "2x1", multiple=1)

    assert result["max_prize"] == 200_000.0
    assert calculate_winning_prize(items, "2x1", multiple=1) == 200_000.0


def test_calculation_rejects_ticket_over_twenty_thousand_yuan():
    items = [
        {"match_id": match_id, "play_type": "spf", "option_code": str(option), "sp_value": 2.0}
        for match_id in range(1, 5)
        for option in range(5)
    ]

    with pytest.raises(ValueError, match="单票金额不得超过20000元"):
        calculate_all(items, "4x1", multiple=50)


@pytest.mark.parametrize("multiple", [0, 51])
def test_calculation_rejects_multiple_outside_one_to_fifty(multiple):
    with pytest.raises(ValueError, match="倍数必须在1到50之间"):
        calculate_all(_items(1), "single", multiple=multiple)
