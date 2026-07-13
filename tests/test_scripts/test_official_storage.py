from unittest.mock import MagicMock

from scripts.official_storage import store_matches


def test_store_matches_rejects_rows_without_canonical_official_identity():
    conn = MagicMock()

    result = store_matches(
        conn,
        [
            {
                "business_date": "2026-07-13",
                "official_match_code": "",
                "source_match_id": None,
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2026-07-13T20:00:00",
            }
        ],
    )

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["errors"] == [
        {
            "match_code": "",
            "error": "missing or invalid Sporttery match code",
        }
    ]
    conn.cursor.assert_not_called()


def test_store_matches_rejects_rows_without_official_match_id():
    conn = MagicMock()

    result = store_matches(
        conn,
        [
            {
                "business_date": "2026-07-13",
                "official_match_code": "周日001",
                "source_match_id": None,
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2026-07-13T20:00:00",
            }
        ],
    )

    assert result["errors"] == [
        {
            "match_code": "周日001",
            "error": "missing Sporttery matchId",
        }
    ]
    conn.cursor.assert_not_called()
