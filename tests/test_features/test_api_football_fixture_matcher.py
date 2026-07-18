from datetime import datetime

from scripts.features.api_football_fixture_matcher import find_matching_fixture


def test_fixture_match_requires_league_time_and_both_team_aliases():
    match = {
        "home_team_id": 11,
        "away_team_id": 12,
        "kickoff_time": datetime(2026, 7, 19, 22, 30),
        "api_league_id": 113,
    }
    fixtures = [
        {
            "fixture": {"id": 99, "date": "2026-07-19T22:30:00+08:00"},
            "league": {"id": 113},
            "teams": {
                "home": {"name": "IF Elfsborg"},
                "away": {"name": "Sirius"},
            },
        },
        {
            "fixture": {"id": 100, "date": "2026-07-19T22:30:00+08:00"},
            "league": {"id": 113},
            "teams": {
                "home": {"name": "Hammarby FF"},
                "away": {"name": "Degerfors IF"},
            },
        },
    ]
    aliases = {
        "IF Elfsborg": 11,
        "Sirius": 12,
        "Hammarby FF": 21,
        "Degerfors IF": 22,
    }

    fixture = find_matching_fixture(match, fixtures, aliases)

    assert fixture is not None
    assert fixture["fixture"]["id"] == 99


def test_fixture_match_rejects_unmapped_team_even_when_time_matches():
    match = {
        "home_team_id": 11,
        "away_team_id": 12,
        "kickoff_time": datetime(2026, 7, 19, 22, 30),
        "api_league_id": 113,
    }
    fixtures = [
        {
            "fixture": {"id": 99, "date": "2026-07-19T22:30:00+08:00"},
            "league": {"id": 113},
            "teams": {
                "home": {"name": "IF Elfsborg"},
                "away": {"name": "Unknown"},
            },
        }
    ]

    assert find_matching_fixture(match, fixtures, {"IF Elfsborg": 11}) is None
