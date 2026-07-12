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
