from __future__ import annotations

from datetime import datetime

from scripts.upset.review import build_review_payload, validate_review_payload
from scripts.upset.review_storage import normalized_fraction


def test_feature_quality_normalizes_legacy_percentage_scale():
    assert normalized_fraction(30) == 0.3
    assert normalized_fraction(0.76) == 0.76
    assert normalized_fraction(None) is None


def test_review_keeps_facts_prematch_signals_and_inferences_separate():
    kickoff = datetime(2026, 7, 20, 12)
    evidence = [
        {
            "id": 1,
            "factor_category": "official_result",
            "factor_code": "final_score",
            "factor_value_json": {"text": "官方赛果为主队1:2客队"},
            "evidence_phase": "postmatch",
            "available_before_kickoff": False,
            "available_at": datetime(2026, 7, 20, 14),
            "verification_status": "verified",
        },
        {
            "id": 2,
            "factor_category": "market",
            "factor_code": "closing_probability",
            "factor_value_json": {"text": "客胜临场去水概率为18.0%"},
            "evidence_phase": "prematch",
            "available_before_kickoff": True,
            "available_at": datetime(2026, 7, 20, 11, 30),
            "verification_status": "verified",
        },
    ]

    payload = build_review_payload(
        event={"upset_level": "A", "home_team_name": "主队", "away_team_name": "客队"},
        evidence=evidence,
        kickoff_time=kickoff,
        model_postmortem={"status": "unavailable"},
    )

    assert payload["facts_json"] == [
        {"text": "官方赛果为主队1:2客队", "evidence_id": 1},
        {"text": "客胜临场去水概率为18.0%", "evidence_id": 2},
    ]
    assert payload["prematch_signals_json"] == [
        {"text": "客胜临场去水概率为18.0%", "evidence_id": 2}
    ]
    assert payload["inferences_json"] == []
    assert payload["hypotheses_json"] == []


def test_validator_rejects_untraceable_fact():
    errors = validate_review_payload(
        {"facts_json": [{"text": "没有证据的事实"}], "prematch_signals_json": []},
        evidence_by_id={},
        kickoff_time=datetime(2026, 7, 20, 12),
    )

    assert "FACT_WITHOUT_EVIDENCE" in errors


def test_validator_rejects_future_information_as_prematch_signal():
    errors = validate_review_payload(
        {
            "facts_json": [{"text": "赛后确认", "evidence_id": 8}],
            "prematch_signals_json": [{"text": "错误赛前信号", "evidence_id": 8}],
        },
        evidence_by_id={
            8: {
                "available_before_kickoff": False,
                "available_at": datetime(2026, 7, 20, 13),
            }
        },
        kickoff_time=datetime(2026, 7, 20, 12),
    )

    assert "PREMATCH_USES_FUTURE_EVIDENCE" in errors


def test_review_explicitly_waits_when_only_base_facts_exist():
    payload = build_review_payload(
        event={"upset_level": "B", "home_team_name": "主队", "away_team_name": "客队"},
        evidence=[],
        kickoff_time=datetime(2026, 7, 20, 12),
        model_postmortem={"status": "unavailable"},
    )

    assert payload["summary"] == "该场已识别为B级冷门，暂无充分证据解释形成原因。"
    assert payload["validation_status"] == "waiting_data"


def test_review_places_verified_in_match_events_in_turning_points():
    kickoff = datetime(2026, 7, 20, 12)
    evidence = [
        {
            "id": 9,
            "factor_category": "match_event",
            "factor_code": "red_card:31:101",
            "factor_value_json": {"text": "第31分钟主队球员张三被红牌罚下"},
            "evidence_phase": "in_match",
            "available_before_kickoff": False,
            "available_at": datetime(2026, 7, 20, 14),
            "verification_status": "verified",
        }
    ]

    payload = build_review_payload(
        event={"upset_level": "A", "home_team_name": "主队", "away_team_name": "客队"},
        evidence=evidence,
        kickoff_time=kickoff,
        model_postmortem={"status": "unavailable"},
    )

    assert payload["in_match_turning_points_json"] == [
        {"text": "第31分钟主队球员张三被红牌罚下", "evidence_id": 9}
    ]


def test_review_counts_postmatch_statistics_but_hides_capture_metadata_from_facts():
    kickoff = datetime(2026, 7, 20, 12)
    evidence = [
        {
            "id": 10,
            "factor_category": "technical_statistics",
            "factor_value_json": {"text": "主队射门18次；客队射门7次"},
            "evidence_phase": "postmatch",
            "available_before_kickoff": False,
            "available_at": datetime(2026, 7, 20, 14),
            "verification_status": "verified",
        },
        {
            "id": 11,
            "factor_category": "provider_capture",
            "factor_value_json": {"text": "赛后辅助比赛数据已完成采集"},
            "evidence_phase": "postmatch",
            "available_before_kickoff": False,
            "available_at": datetime(2026, 7, 20, 14),
            "verification_status": "verified",
        },
    ]

    payload = build_review_payload(
        event={"upset_level": "B"},
        evidence=evidence,
        kickoff_time=kickoff,
        model_postmortem={"status": "unavailable"},
    )

    assert payload["facts_json"] == [
        {"text": "主队射门18次；客队射门7次", "evidence_id": 10}
    ]
    assert payload["data_completeness"] == 0.05
