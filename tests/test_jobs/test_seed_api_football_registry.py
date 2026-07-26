from unittest.mock import patch

from scripts.jobs.seed_api_football_registry import run


def test_registry_seeds_competitions_before_team_aliases():
    with (
        patch(
            "scripts.jobs.seed_api_football_registry.seed_competitions",
            return_value={"status": "ok", "competitions_created": 1},
        ) as competitions,
        patch(
            "scripts.jobs.seed_api_football_registry.seed_team_aliases",
            return_value={"status": "ok", "aliases_added": 2},
        ) as aliases,
    ):
        result = run()

    assert competitions.call_count == 1
    assert aliases.call_count == 1
    assert result["status"] == "ok"
    assert result["competitions"]["competitions_created"] == 1
    assert result["aliases"]["aliases_added"] == 2
