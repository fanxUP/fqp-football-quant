from scripts.jobs.settle_tickets import _normalize_result


def test_normalizes_win_draw_loss_and_half_full_codes():
    assert _normalize_result("spf", "H") == "3"
    assert _normalize_result("rqspf", "a") == "0"
    assert _normalize_result("bqc", "ha") == "30"


def test_normalizes_seven_plus_goals():
    assert _normalize_result("zjq", "7+") == "7"
