from unittest.mock import MagicMock

from scripts.features.stadium_resolver import resolve_match_stadium_location


def test_resolver_prioritizes_official_neutral_venue_remark():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (11, 25.958, -80.238)

    location = resolve_match_stadium_location(
        conn,
        raw_json={"remark": "比赛将在美国-佛罗里达州迈阿密加登斯举行"},
        home_team_name="法国",
    )

    assert location == {
        "stadium_id": 11,
        "latitude": 25.958,
        "longitude": -80.238,
        "source": "official_venue_remark",
    }


def test_resolver_uses_primary_home_team_stadium_without_hardcoded_job_logic():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (12, 37.5247, 126.7897)

    location = resolve_match_stadium_location(
        conn,
        raw_json={},
        home_team_name="富川FC",
    )

    assert location == {
        "stadium_id": 12,
        "latitude": 37.5247,
        "longitude": 126.7897,
        "source": "home_team_stadium",
    }
