from scripts.simulator_calculator import (
    calculate_all,
    calculate_bet_combinations,
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
