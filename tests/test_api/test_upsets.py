from __future__ import annotations

from unittest.mock import patch


def test_upset_list_exposes_filters_and_pagination(client):
    rows = [
        {
            "id": 7,
            "business_date": "2026-07-20",
            "official_match_code": "周一201",
            "league_name": "测试联赛",
            "home_team_name": "主队",
            "away_team_name": "客队",
            "full_score": "1:2",
            "upset_level": "A",
            "primary_play_type": "spf",
            "actual_outcome_probability": 0.18,
        }
    ]
    with patch("apps.backend.src.routers.upsets.list_upsets", return_value=(rows, 23)) as query:
        response = client.get(
            "/api/upsets?start_date=2026-07-01&end_date=2026-07-20"
            "&league_name=测试联赛&level=A&play_type=spf&agent_involved=true&limit=10&offset=20"
        )

    assert response.status_code == 200
    assert response.json() == {"items": rows, "total": 23, "limit": 10, "offset": 20}
    assert query.call_args.kwargs == {
        "start_date": "2026-07-01",
        "end_date": "2026-07-20",
        "league_name": "测试联赛",
        "level": "A",
        "play_type": "spf",
        "user_involved": None,
        "agent_involved": True,
        "review_status": None,
        "limit": 10,
        "offset": 20,
    }


def test_upset_summary_returns_market_and_betting_counts(client):
    summary = {
        "settled_match_count": 100,
        "upset_count": 24,
        "upset_rate": 0.24,
        "severe_count": 8,
        "user_involved_count": 3,
        "agent_involved_count": 5,
        "level_counts": {"S": 2, "A": 6, "B": 9, "C": 7},
    }
    with patch("apps.backend.src.routers.upsets.get_upset_summary", return_value=summary):
        response = client.get(
            "/api/upsets/summary?start_date=2026-07-01&end_date=2026-07-20"
        )

    assert response.status_code == 200
    assert response.json() == summary


def test_upset_detail_returns_404_for_unknown_event(client):
    with patch("apps.backend.src.routers.upsets.get_upset_detail", return_value=None):
        response = client.get("/api/upsets/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "冷门事件不存在"


def test_upset_detail_returns_signals_evidence_review_and_tickets(client):
    detail = {
        "event": {"id": 7, "upset_level": "A"},
        "market_signals": [{"play_type": "spf"}],
        "evidence": [],
        "review": None,
        "user_tickets": [],
        "agent_tickets": [{"ticket_id": 91, "profit_loss": -198}],
    }
    with patch("apps.backend.src.routers.upsets.get_upset_detail", return_value=detail):
        response = client.get("/api/upsets/7")

    assert response.status_code == 200
    assert response.json() == detail
