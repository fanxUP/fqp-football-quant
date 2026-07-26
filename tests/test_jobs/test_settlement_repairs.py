from scripts.jobs.settlement_repairs import correct_legacy_settlement_detail


def test_corrects_legacy_result_codes_and_recalculates_mixed_pass_prize():
    detail = {
        "source": "real",
        "pass_type": "2x1,3x1,4x1",
        "multiple": 1,
        "items": [
            {
                "match_id": 1,
                "play_type": "spf",
                "option_code": "h",
                "actual_result": "0",
                "sp_value": 2.44,
                "is_won": False,
            },
            {
                "match_id": 2,
                "play_type": "spf",
                "option_code": "h",
                "actual_result": "void",
                "sp_value": 1.0,
                "is_void": True,
                "is_won": True,
            },
            {
                "match_id": 3,
                "play_type": "rqspf",
                "option_code": "a",
                "actual_result": "0",
                "sp_value": 2.52,
                "is_won": False,
            },
            {
                "match_id": 4,
                "play_type": "rqspf",
                "option_code": "a",
                "actual_result": "1",
                "sp_value": 2.7,
                "is_won": False,
            },
        ],
    }

    corrected = correct_legacy_settlement_detail(detail, stake=22.0)

    assert corrected is not None
    assert corrected["prize_amount"] == 5.04
    assert corrected["profit_loss"] == -16.96
    assert corrected["detail"]["items"][2]["option_code"] == "0"
    assert corrected["detail"]["items"][2]["original_option_code"] == "a"
    assert corrected["detail"]["items"][2]["is_won"] is True


def test_numeric_settlement_detail_needs_no_legacy_repair():
    detail = {
        "pass_type": "single",
        "multiple": 1,
        "items": [
            {
                "match_id": 1,
                "play_type": "spf",
                "option_code": "3",
                "actual_result": "3",
                "sp_value": 2.0,
                "is_won": True,
            }
        ],
    }

    assert correct_legacy_settlement_detail(detail, stake=2.0) is None
