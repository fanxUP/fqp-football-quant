from unittest.mock import ANY, MagicMock, patch

from scripts.official_crawler import (
    crawl_official_odds_snapshot,
    crawl_official_results,
    parse_matches_from_response,
    parse_odds_snapshots_from_match,
    parse_results_from_response,
)


def test_parse_uniform_match_keeps_official_display_code_and_sale_status():
    raw = {
        "value": {
            "matchInfoList": [
                {
                    "businessDate": "2026-07-10",
                    "subMatchList": [
                        {
                            "matchNum": 5098,
                            "matchNumStr": "周五098",
                            "matchDate": "2026-07-11",
                            "matchTime": "03:00",
                            "leagueAllName": "世界杯",
                            "homeTeamAllName": "西班牙",
                            "awayTeamAllName": "比利时",
                            "sellStatus": "1",
                            "matchStatus": "Selling",
                            "oddsList": [],
                        }
                    ],
                }
            ]
        }
    }

    match = parse_matches_from_response(raw, "2026-07-10")[0]

    assert match["official_match_code"] == "周五098"
    assert match["sale_status"] == "selling"
    assert match["match_status"] == "scheduled"


def test_current_pool_flags_drive_single_and_pass_availability():
    sub_match = {
        "matchNumStr": "周日203",
        "matchDate": "2026-07-12",
        "matchTime": "18:30",
        "leagueAllName": "韩国职业联赛",
        "homeTeamAllName": "首尔FC",
        "awayTeamAllName": "江原FC",
        "sellStatus": "1",
        "oddsList": [{"poolCode": "CRS", "h": 8.5, "d": 5.5, "a": 7.3}],
        "poolList": [{"poolCode": "CRS", "cbtSingle": 1, "cbtAllUp": 1}],
    }
    raw = {"value": {"matchInfoList": [{"businessDate": "2026-07-12", "subMatchList": [sub_match]}]}}

    match = parse_matches_from_response(raw, "2026-07-12")[0]
    market = match["_markets"][0]
    snapshots = parse_odds_snapshots_from_match(sub_match, "2026-07-12T12:00:00")

    assert market["is_single_allowed"] is True
    assert market["is_pass_allowed"] is True
    assert market["raw_json"]["_pool"]["cbtSingle"] == 1
    assert all(snapshot["is_single_allowed"] is True for snapshot in snapshots)
    assert all(snapshot["is_pass_allowed"] is True for snapshot in snapshots)


def test_missing_pool_code_is_ignored_and_missing_permissions_fail_closed():
    sub_match = {
        "matchNumStr": "周一201",
        "matchDate": "2026-07-14",
        "matchTime": "01:00",
        "leagueAllName": "测试联赛",
        "homeTeamAllName": "主队",
        "awayTeamAllName": "客队",
        "sellStatus": "1",
        "oddsList": [
            {"poolCode": "", "h": 2.0, "d": 3.0, "a": 4.0},
            {"poolCode": "HAD", "h": 2.1, "d": 3.1, "a": 4.1},
        ],
        "poolList": [],
    }
    raw = {"value": {"matchInfoList": [{"businessDate": "2026-07-13", "subMatchList": [sub_match]}]}}

    match = parse_matches_from_response(raw, "2026-07-13")[0]
    snapshots = parse_odds_snapshots_from_match(sub_match, "2026-07-13T12:00:00")

    assert [market["play_type"] for market in match["_markets"]] == ["spf"]
    assert {snapshot["play_type"] for snapshot in snapshots} == {"spf"}
    assert all(snapshot["is_single_allowed"] is False for snapshot in snapshots)
    assert all(snapshot["is_pass_allowed"] is False for snapshot in snapshots)


def test_blocked_sporttery_results_use_labeled_500_supplement_for_existing_official_matches():
    client = MagicMock()
    client.get_match_results.side_effect = RuntimeError("403 Forbidden")
    connection = MagicMock()
    supplemental_result = {"match_id": 12, "raw_json": {"provider_id": "500-match-1"}}

    with patch("scripts.official_crawler.SportteryClient", return_value=client), \
         patch("scripts.official_crawler.get_db") as get_db, \
         patch("scripts.official_crawler.record_official_collection_status") as record_status, \
         patch("scripts.official_crawler.log_crawl"), \
         patch("scripts.official_crawler.update_health") as update_health, \
         patch("scripts.official_crawler.get_results_via_500", return_value=[supplemental_result]), \
         patch("scripts.official_crawler.store_results", return_value={"inserted": 1, "updated": 0}) as store_results:
        get_db.return_value.__enter__.return_value = connection

        result = crawl_official_results("2026-07-10", "2026-07-11")

    assert result["status"] == "ok"
    assert result["source"] == "500.com"
    assert result["source_type"] == "supplemental"
    assert supplemental_result["raw_json"]["source_name"] == "500.com"
    assert supplemental_result["raw_json"]["official_match_verified"] is True
    store_results.assert_called_once_with(connection, [supplemental_result])
    record_status.assert_called_once()
    update_health.assert_any_call(connection, "sporttery", "official", "error", 0, ANY)
    update_health.assert_any_call(connection, "500.com", "supplemental", "ok", ANY)


def test_parse_official_result_preserves_numeric_zero_scores():
    raw = {
        "value": {
            "matchResultList": [
                {
                    "matchNumStr": "周五098",
                    "halfHomeGoals": 0,
                    "halfAwayGoals": 0,
                    "fullHomeGoals": 0,
                    "fullAwayGoals": 1,
                }
            ]
        }
    }

    result = parse_results_from_response(raw)[0]

    assert result["half_home_goals"] == 0
    assert result["half_away_goals"] == 0
    assert result["full_home_goals"] == 0
    assert result["full_away_goals"] == 1
    assert result["score_result"] == "0:1"
    assert result["spf_result"] == "0"


def test_odds_snapshot_uses_fixed_bonus_history_when_sporttery_match_id_exists():
    client = MagicMock()
    client.get_daily_matches.return_value = {}
    client.get_uniform_fixed_bonus.return_value = {"value": {"oddsHistory": {}}}
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (12, "2040374")
    matches = [{"official_match_code": "周五098", "business_date": "2026-07-10"}]

    with patch("scripts.official_crawler.SportteryClient", return_value=client), \
         patch("scripts.official_crawler.parse_matches_from_response", return_value=matches), \
         patch("scripts.official_crawler.get_db") as get_db, \
         patch("scripts.official_crawler.store_fixed_bonus_history", return_value={"inserted": 9}), \
         patch("scripts.official_crawler.log_crawl"), \
         patch("scripts.official_crawler.update_health"):
        get_db.return_value.__enter__.return_value = connection

        result = crawl_official_odds_snapshot("2026-07-10")

    assert result["status"] == "ok"
    assert result["snapshots_inserted"] == 9
    client.get_uniform_fixed_bonus.assert_called_once_with(2040374)
