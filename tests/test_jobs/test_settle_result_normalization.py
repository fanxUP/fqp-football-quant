from scripts.jobs.settle_tickets import (
    _calculate_agent_prize,
    _normalize_result,
    _resolve_ticket_items,
)
from scripts.simulator_calculator import calculate_winning_prize


def test_normalizes_win_draw_loss_and_half_full_codes():
    assert _normalize_result("spf", "H") == "3"
    assert _normalize_result("rqspf", "a") == "0"
    assert _normalize_result("bqc", "ha") == "30"


def test_normalizes_seven_plus_goals():
    assert _normalize_result("zjq", "7+") == "7"


def test_normalizes_score_separator_and_half_full_separator():
    assert _normalize_result("bf", "3-0") == "3:0"
    assert _normalize_result("bqc", "H/A") == "30"


def test_resolves_mixed_play_results_and_same_match_alternatives():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 2.0},
        {"match_id": 1, "play_type": "spf", "option_code": "1", "sp_value": 3.0},
        {"match_id": 2, "play_type": "zjq", "option_code": "3", "sp_value": 2.5},
    ]
    results = {
        1: {"spf_result": "H"},
        2: {"total_goals_result": "3"},
    }

    detail = _resolve_ticket_items(items, results)

    assert detail is not None
    assert [item["is_won"] for item in detail] == [True, False, True]
    assert calculate_winning_prize(detail, "2x1", multiple=1) == 10.0


def test_normalizes_legacy_ticket_option_before_comparing_result():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "h", "sp_value": 2.0},
    ]

    detail = _resolve_ticket_items(items, {1: {"spf_result": "H"}})

    assert detail is not None
    assert detail[0]["option_code"] == "3"
    assert detail[0]["original_option_code"] == "h"
    assert detail[0]["is_won"] is True


def test_waits_when_selected_play_result_is_not_available():
    items = [
        {"match_id": 1, "play_type": "rqspf", "option_code": "3", "sp_value": 2.0},
    ]

    assert _resolve_ticket_items(items, {1: {"spf_result": "H", "rqspf_result": None}}) is None


def test_void_match_refunds_every_selection_at_odds_one():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 2.4},
        {"match_id": 1, "play_type": "spf", "option_code": "0", "sp_value": 3.1},
    ]
    results = {1: {"is_void": True, "spf_result": None}}

    detail = _resolve_ticket_items(items, results)

    assert detail is not None
    assert [item["is_void"] for item in detail] == [True, True]
    assert [item["is_won"] for item in detail] == [True, True]
    assert [item["sp_value"] for item in detail] == [1.0, 1.0]
    assert [item["original_sp_value"] for item in detail] == [2.4, 3.1]
    assert calculate_winning_prize(detail, "single", multiple=1) == 4.0


def test_void_match_is_removed_from_parlay_odds():
    items = [
        {"match_id": 1, "play_type": "spf", "option_code": "3", "sp_value": 2.4},
        {"match_id": 2, "play_type": "spf", "option_code": "0", "sp_value": 1.8},
    ]
    results = {
        1: {"is_void": True, "spf_result": None},
        2: {"is_void": False, "spf_result": "0"},
    }

    detail = _resolve_ticket_items(items, results)

    assert detail is not None
    assert calculate_winning_prize(detail, "2x1", multiple=1) == 3.6


def test_derives_rqspf_result_from_ticket_handicap_and_final_score():
    items = [
        {
            "match_id": 1,
            "play_type": "rqspf",
            "option_code": "0",
            "sp_value": 1.58,
            "handicap": -1,
        },
    ]
    results = {
        1: {
            "spf_result": "0",
            "rqspf_result": None,
            "full_home_goals": 0,
            "full_away_goals": 2,
        }
    }

    detail = _resolve_ticket_items(items, results)

    assert detail is not None
    assert detail[0]["actual_result"] == "0"
    assert detail[0]["is_won"] is True


def test_waits_for_rqspf_when_ticket_handicap_is_missing():
    items = [
        {"match_id": 1, "play_type": "rqspf", "option_code": "0", "sp_value": 1.58},
    ]
    results = {
        1: {
            "spf_result": "0",
            "rqspf_result": None,
            "full_home_goals": 0,
            "full_away_goals": 2,
        }
    }

    assert _resolve_ticket_items(items, results) is None


def test_agent_prize_scales_from_nominal_cost_to_committed_stake():
    detail = [
        {
            "match_id": 1,
            "play_type": "spf",
            "option_code": "3",
            "sp_value": 2.5,
            "is_dan": False,
            "actual_result": "3",
            "is_won": True,
        }
    ]

    assert _calculate_agent_prize(detail, "single", 1, bet_count=1, stake=20) == 50.0
