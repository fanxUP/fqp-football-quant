from datetime import datetime

from scripts.upset.provider_evidence import (
    build_event_evidence_values,
    build_statistics_evidence_values,
)


def test_api_football_events_are_normalized_into_turning_points():
    values = build_event_evidence_values(
        [
            {
                "time": {"elapsed": 31, "extra": None},
                "team": {"id": 101},
                "player": {"name": "张三"},
                "type": "Card",
                "detail": "Red Card",
            },
            {
                "time": {"elapsed": 48, "extra": 2},
                "team": {"id": 202},
                "player": {"name": "李四"},
                "type": "Goal",
                "detail": "Normal Goal",
            },
            {
                "time": {"elapsed": 70},
                "team": {"id": 101},
                "type": "subst",
                "detail": "Substitution 1",
            },
        ],
        team_names_by_api_id={101: "主队", 202: "客队"},
    )

    assert [item["factor_code"] for item in values] == [
        "red_card:31:101",
        "goal:48+2:202",
    ]
    assert values[0]["text"] == "第31分钟主队球员张三被红牌罚下"
    assert values[1]["text"] == "第48+2分钟客队球员李四取得进球"
    assert all(item["evidence_phase"] == "in_match" for item in values)


def test_api_football_statistics_keep_only_supported_non_empty_metrics():
    values = build_statistics_evidence_values(
        [
            {
                "team": {"id": 101},
                "statistics": [
                    {"type": "Shots on Goal", "value": 5},
                    {"type": "Total Shots", "value": 18},
                    {"type": "Ball Possession", "value": "61%"},
                    {"type": "expected_goals", "value": "2.14"},
                    {"type": "Blocked Shots", "value": None},
                ],
            },
            {
                "team": {"id": 202},
                "statistics": [
                    {"type": "Shots on Goal", "value": 4},
                    {"type": "Total Shots", "value": 7},
                    {"type": "Ball Possession", "value": "39%"},
                    {"type": "expected_goals", "value": "1.32"},
                ],
            },
        ],
        team_names_by_api_id={101: "主队", 202: "客队"},
    )

    assert len(values) == 1
    assert values[0]["factor_code"] == "match_technical_statistics"
    assert len(values[0]["factor_value_json"]["teams"]) == 2
    assert "主队射正5次、射门18次、控球率61%、预期进球2.14" in values[0]["text"]
    assert "客队射正4次、射门7次、控球率39%、预期进球1.32" in values[0]["text"]
    assert values[0]["evidence_phase"] == "postmatch"


def test_provider_evidence_timestamps_remain_post_kickoff():
    values = build_event_evidence_values(
        [],
        team_names_by_api_id={},
        observed_at=datetime(2026, 7, 20, 15),
    )

    assert values == []
