from unittest.mock import MagicMock, patch

from scripts.jobs.collect_lineup_data import _process_lineup


def test_api_fixture_lineup_is_stored_as_confirmed():
    conn = MagicMock()
    team_data = {
        "formation": "4-3-3",
        "startXI": [{"player": {"id": 1, "name": "Starter", "pos": "G"}}],
        "substitutes": [],
    }

    with (
        patch("scripts.jobs.collect_lineup_data._get_or_create_player", return_value=101),
        patch(
            "scripts.jobs.collect_lineup_data.store_match_lineup_snapshot",
            return_value=501,
        ) as store_snapshot,
        patch("scripts.jobs.collect_lineup_data.store_match_lineup_player"),
    ):
        result = _process_lineup(conn, 7, team_data, 11, "2026-07-19T04:30:00")

    assert result == 501
    snapshot = store_snapshot.call_args.args[1]
    assert snapshot["lineup_type"] == "confirmed"
    assert snapshot["lineup_uncertainty_score"] <= 10
