from unittest.mock import MagicMock

from scripts.official_storage import store_matches, store_results


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


def test_store_matches_rejects_numbered_match_outside_selected_event_season():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("世界杯", "2026-06-11", "2026-07-20"),
    ]

    result = store_matches(
        conn,
        [
            {
                "business_date": "2022-11-20",
                "official_match_code": "周日001",
                "source_match_id": "10001",
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2022-11-20T20:00:00",
            }
        ],
    )

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["errors"] == [
        {
            "match_code": "周日001",
            "error": "outside selected event season",
        }
    ]
    assert cursor.execute.call_count == 1


def test_confirmed_result_closes_match_sales_even_when_match_was_already_settled():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (9, True)

    result = store_results(
        conn,
        [
            {
                "match_id": 7,
                "result_status": "confirmed",
                "full_home_goals": 2,
                "full_away_goals": 1,
            }
        ],
    )

    close_query = cursor.execute.call_args_list[-1].args[0]
    assert "sale_status = 'closed'" in close_query
    assert "sale_status IS DISTINCT FROM 'closed'" in close_query
    assert result["settled"] == 1
