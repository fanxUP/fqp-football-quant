from datetime import datetime

from scripts.features.build_upset_risk import (
    build_upset_risk_features,
    load_pre_kickoff_upset_risk,
)


def test_upset_risk_uses_shrunk_historical_rates_and_reports_confidence():
    features = build_upset_risk_features(
        {
            "global_upset_count": 20,
            "global_match_count": 100,
            "league_upset_count": 8,
            "league_match_count": 20,
            "home_upset_count": 3,
            "home_match_count": 10,
            "away_upset_count": 1,
            "away_match_count": 10,
        }
    )

    assert features["upset_risk_score"] == 0.266667
    assert features["league_upset_rate"] == 0.333333
    assert features["home_team_upset_rate"] == 0.25
    assert features["away_team_upset_rate"] == 0.15
    assert features["upset_risk_confidence"] == 0.444444


def test_upset_risk_is_missing_when_history_cannot_support_a_feature():
    features = build_upset_risk_features(
        {
            "global_upset_count": 2,
            "global_match_count": 8,
            "league_upset_count": 1,
            "league_match_count": 4,
            "home_upset_count": 1,
            "home_match_count": 2,
            "away_upset_count": 0,
            "away_match_count": 2,
        }
    )

    assert features == {
        "upset_risk_score": None,
        "league_upset_rate": None,
        "home_team_upset_rate": None,
        "away_team_upset_rate": None,
        "upset_risk_confidence": None,
        "upset_risk_sample_size": 0,
    }


def test_upset_risk_loader_excludes_matches_at_or_after_kickoff(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = {
        "global_upset_count": 10,
        "global_match_count": 50,
        "league_upset_count": 3,
        "league_match_count": 15,
        "home_upset_count": 2,
        "home_match_count": 10,
        "away_upset_count": 2,
        "away_match_count": 10,
    }

    features = load_pre_kickoff_upset_risk(
        conn,
        league_name="测试联赛",
        home_team_id=11,
        away_team_id=22,
        kickoff_time=datetime(2026, 8, 9, 20, 0),
    )

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "historical.kickoff_time < %(kickoff_time)s" in query
    assert cur.execute.call_args.args[1]["kickoff_time"] == datetime(2026, 8, 9, 20, 0)
    assert features["upset_risk_sample_size"] == 50
