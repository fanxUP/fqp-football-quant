from unittest.mock import patch

from scripts.jobs.seed_stadium_registry import run


def test_registry_stays_blocked_until_team_stadium_mappings_exist():
    with (
        patch(
            "scripts.features.populate_teams_leagues.populate_all",
            return_value={"teams_created": 0},
        ),
        patch(
            "scripts.seed_stadiums.run",
            return_value={"status": "blocked", "mappings_total": 0},
        ),
    ):
        result = run()

    assert result["status"] == "blocked"
    assert result["stadiums"]["mappings_total"] == 0
