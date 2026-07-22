from datetime import datetime
from unittest.mock import MagicMock

from scripts.feature_storage import store_team_season_profile


def test_team_profile_storage_uses_current_snapshot_schema():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (17,)

    profile_id = store_team_season_profile(
        conn,
        {
            "team_id": 3,
            "competition_season_id": 5,
            "snapshot_time": datetime(2026, 7, 14, 15, 0),
            "attack_strength_score": 1.8,
            "defense_strength_score": 0.9,
            "data_source": "computed_form",
            "data_confidence": 0.7,
            "raw_json": {"matches_played": 8, "wins": 5},
        },
    )

    sql = cur.execute.call_args.args[0]
    assert profile_id == 17
    assert "snapshot_time" in sql
    assert "data_source" in sql
    assert "season_code" not in sql
    assert "matches_played" not in sql
    assert "ON CONFLICT" in sql


def test_team_profile_requires_competition_season():
    conn = MagicMock()

    assert store_team_season_profile(conn, {"team_id": 3}) is None
    conn.cursor.assert_not_called()
