from unittest.mock import patch

from scripts.jobs import collect_standings


def test_standings_compatibility_job_uses_verified_current_sources():
    with (
        patch.object(
            collect_standings, "seed_official_team_aliases", return_value={"status": "ok"}
        ),
        patch.object(
            collect_standings,
            "collect_official_standings",
            return_value={"status": "ok", "reports": []},
        ) as collect,
    ):
        result = collect_standings.run(season=2024)

    collect.assert_called_once_with(dry_run=False)
    assert result["source_policy"] == "verified_official_current_season"
    assert result["requested_season"] == 2024
