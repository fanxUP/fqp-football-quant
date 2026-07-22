from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from scripts.jobs import run_recommendation_candidate as recommendation
from scripts.jobs.run_recommendation_candidate import (
    _build_competition_observation_ticket,
    _buy_ticket,
    _market_allows_pass,
    _market_sp_quality,
    _no_candidate_note,
    _option_label,
    _prediction_sp_value,
    _preferred_direction_by_market,
    _quality_risk_penalty,
    _ticket_generation_note,
)
from scripts.recommendation_prediction_loader import load_actionable_predictions
from scripts.sporttery_sales import get_sporttery_sales_window


def test_agent_does_not_buy_during_official_rest_time(monkeypatch):
    rest_window = get_sporttery_sales_window(
        datetime(2026, 7, 19, 2, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    get_db = MagicMock()
    monkeypatch.setattr(recommendation, "get_db", get_db)
    monkeypatch.setattr(
        recommendation,
        "get_sporttery_sales_window",
        lambda: rest_window,
        raising=False,
    )

    assert recommendation._run_impl() == {
        "status": "ok",
        "tickets": 0,
        "quality_status": "not_due",
        "note": rest_window.message,
        "sales_window": rest_window.as_dict(),
    }
    get_db.assert_not_called()


def test_actionable_predictions_are_latest_per_match_model_play_and_option(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = []

    assert load_actionable_predictions(conn, recommendation.ALL_MODELS) == []

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "DISTINCT ON (" in query
    assert "mp.match_id, mp.model_version_id, mp.play_type, mp.option_code" in query
    assert "mp.predict_time < m.kickoff_time" in query
    assert "mp.validation_status = 'valid'" in query
    assert "model_independent" in query
    assert "m.kickoff_time > timezone('Asia/Shanghai', NOW())" in query
    assert "SELECT MAX(predict_time)" not in query
    assert "mp.model_probability * latest_os.sp_value - 1" in query
    assert "latest_os.id" in query
    assert "CASE WHEN mp.play_type IN ('spf', 'rqspf') THEN CASE mp.option_code" in query


def test_prediction_sp_value_does_not_treat_kickoff_as_sp():
    row = tuple(range(15)) + (datetime(2026, 7, 11, 3), 1.46, "market_baseline")

    assert _prediction_sp_value(row) == 1.46


def test_low_quality_prediction_is_forced_out_of_normal_staking_pools() -> None:
    assert _quality_risk_penalty(30) == 1.0
    assert _quality_risk_penalty(49.9) == 1.0
    assert _quality_risk_penalty(50) == 0.0


def test_preferred_direction_never_compares_different_play_types() -> None:
    spf_home = [None] * 18
    spf_home[1], spf_home[3], spf_home[4], spf_home[5] = 7, "spf", "3", 0.55
    total_zero = [None] * 18
    total_zero[1], total_zero[3], total_zero[4], total_zero[5] = 7, "zjq", "0", 0.70

    preferred = _preferred_direction_by_market([tuple(spf_home), tuple(total_zero)])

    assert preferred[(7, "spf")] == ("3", 0.55)
    assert preferred[(7, "zjq")] == ("0", 0.70)


def test_rqspf_option_label_explains_handicap_outcome():
    assert _option_label("3", "rqspf") == "让胜"
    assert _option_label("1", "rqspf") == "让平"
    assert _option_label("0", "rqspf") == "让负"


def test_sp_quality_isolated_by_match_and_play_type():
    def prediction(play_type, option_code, sp_value):
        row = [None] * 18
        row[1] = 7
        row[3] = play_type
        row[4] = option_code
        row[16] = sp_value
        return tuple(row)

    quality, valid_match_count = _market_sp_quality([
        prediction("spf", "3", 2.10),
        prediction("spf", "1", 3.20),
        prediction("spf", "0", 3.40),
        prediction("zjq", "0", 0),
        prediction("zjq", "1", 6.50),
    ])

    assert quality[(7, "spf")] is True
    assert quality[(7, "zjq")] is False
    assert valid_match_count == 1


def test_agent_purchase_uses_agent_ticket_ledger(monkeypatch):
    stored = {}

    def fake_store(conn, ticket, items):
        stored.update({"conn": conn, "ticket": ticket, "items": items})
        return 91

    monkeypatch.setattr(recommendation, "store_simulation_ticket", fake_store)
    conn = object()
    ticket = {"suggested_stake": 20, "strategy_pool": "agent_value"}
    items = [{"match_id": 7}]

    assert _buy_ticket(conn, ticket, items) == 91
    assert stored == {"conn": conn, "ticket": ticket, "items": items}


def test_agent_purchase_rolls_back_failed_ticket_write(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        recommendation,
        "store_simulation_ticket",
        lambda conn, ticket, items: (_ for _ in ()).throw(RuntimeError("write failed")),
    )

    assert _buy_ticket(conn, {"suggested_stake": 20}, [{"match_id": 7}]) is None
    conn.rollback.assert_called_once()


def test_no_candidate_note_exposes_data_quality_rejections():
    note = _no_candidate_note(
        total_predictions=78,
        rejection_counts={"data_quality": 78},
        minimum_quality=50,
    )

    assert note == "数据完整度不足：78 条预测未达到 50 分门槛，今日不投注"


def test_ticket_generation_note_exposes_pool_risk_rejections():
    assert _ticket_generation_note(tickets_created=0, candidate_count=3) == (
        "发现 3 个正 EV 候选，但均未通过资金池风险与置信度门槛，今日不投注"
    )


def test_ticket_generation_note_marks_minimum_competition_observation():
    assert _ticket_generation_note(
        tickets_created=1,
        candidate_count=3,
        observation_fallback=True,
    ) == "常规资金池未放行，已用 2 元生成 1 张高风险虚拟观察票，用于 Agent 竞赛与复盘"


def test_competition_observation_prefers_a_sellable_single():
    candidates = [
        {
            "match_id": 7,
            "play_type": "spf",
            "sp_value": 2.40,
            "ev": 0.20,
            "risk_score": 0.62,
        },
        {
            "match_id": 8,
            "play_type": "rqspf",
            "sp_value": 3.10,
            "ev": 0.18,
            "risk_score": 0.58,
        },
    ]

    fallback = _build_competition_observation_ticket(
        candidates,
        single_allowed={(7, "spf")},
        pass_allowed=set(),
    )

    assert fallback is not None
    ticket, selected = fallback
    assert ticket["strategy_pool"] == "agent_competition_observation"
    assert ticket["pass_type"] == "single"
    assert ticket["suggested_stake"] == 2.0
    assert selected == [candidates[0]]


def test_competition_observation_uses_two_match_parlay_when_single_is_unavailable():
    candidates = [
        {
            "match_id": 7,
            "play_type": "spf",
            "sp_value": 2.40,
            "ev": 0.20,
            "risk_score": 0.62,
        },
        {
            "match_id": 8,
            "play_type": "rqspf",
            "sp_value": 3.10,
            "ev": 0.18,
            "risk_score": 0.58,
        },
    ]

    fallback = _build_competition_observation_ticket(
        candidates,
        single_allowed=set(),
        pass_allowed={(7, "spf"), (8, "rqspf")},
    )

    assert fallback is not None
    ticket, selected = fallback
    assert ticket["pass_type"] == "2x1"
    assert ticket["suggested_stake"] == 2.0
    assert [item["match_id"] for item in selected] == [7, 8]


def test_competition_observation_abstains_without_an_official_bet_route():
    candidates = [
        {"match_id": 7, "play_type": "spf", "sp_value": 2.40, "ev": 0.20},
        {"match_id": 8, "play_type": "rqspf", "sp_value": 3.10, "ev": 0.18},
    ]

    fallback = _build_competition_observation_ticket(
        candidates,
        single_allowed=set(),
        pass_allowed={(7, "spf")},
    )

    assert fallback is None


def test_competition_observation_rejects_zero_sp_candidate():
    candidates = [
        {"match_id": 7, "play_type": "zjq", "sp_value": 0, "ev": 0.20},
    ]

    fallback = _build_competition_observation_ticket(
        candidates,
        single_allowed={(7, "zjq")},
        pass_allowed={(7, "zjq")},
    )

    assert fallback is None


def test_market_allows_pass_reads_current_sporttery_capability_fields():
    assert _market_allows_pass({"_pool": {"cbtAllUp": 1, "intAllUp": 0}}) is True
    assert _market_allows_pass({"_pool": {"cbtAllUp": 0, "intAllUp": 0}}) is False
