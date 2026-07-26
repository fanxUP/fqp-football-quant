from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch

from scripts.official_crawler import (
    crawl_official_odds_snapshot,
    crawl_official_results,
    crawl_official_schedule_v2,
    parse_matches_from_response,
    parse_odds_snapshots_from_match,
    parse_results_from_response,
    parse_traditional_lottery_response,
)


def test_traditional_lottery_sale_status_uses_shanghai_business_time():
    raw = {
        "value": {
            "sfcDetail": {
                "lotteryDrawNum": "26001",
                "saleEndTime": "2026-07-15T03:00:00",
                "matchList": [{"matchId": "1", "homeTeam": "A", "awayTeam": "B"}],
            }
        }
    }
    utc_now = datetime(2026, 7, 14, 20, 0, tzinfo=UTC)

    pools = parse_traditional_lottery_response(raw, now=utc_now)

    assert pools[0]["official_status"] == "closed"


def test_traditional_lottery_reads_official_sale_window_field_names():
    raw = {
        "value": {
            "sfcDetail": {
                "lotteryDrawNum": "26093",
                "lotterySaleBeginTime": "2026-07-18 20:00:00",
                "lotterySaleEndtime": "2026-07-19 22:00:00",
                "matchList": [{"matchId": "1", "homeTeam": "A", "awayTeam": "B"}],
            }
        }
    }
    now = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)

    pools = parse_traditional_lottery_response(raw, now=now)

    assert pools[0]["sale_start"] == "2026-07-18 20:00:00"
    assert pools[0]["sale_stop"] == "2026-07-19 22:00:00"
    assert pools[0]["official_status"] == "selling"


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
    raw = {
        "value": {"matchInfoList": [{"businessDate": "2026-07-12", "subMatchList": [sub_match]}]}
    }

    match = parse_matches_from_response(raw, "2026-07-12")[0]
    market = match["_markets"][0]
    snapshots = parse_odds_snapshots_from_match(sub_match, "2026-07-12T12:00:00")

    assert market["is_single_allowed"] is True
    assert market["is_pass_allowed"] is True
    assert market["raw_json"]["_pool"]["cbtSingle"] == 1
    assert all(snapshot["is_single_allowed"] is True for snapshot in snapshots)
    assert all(snapshot["is_pass_allowed"] is True for snapshot in snapshots)


def test_pool_list_builds_all_official_markets_and_respects_sale_status():
    sub_match = {
        "matchNumStr": "周一202",
        "matchDate": "2026-07-14",
        "matchTime": "02:00",
        "leagueAllName": "测试联赛",
        "homeTeamAllName": "主队",
        "awayTeamAllName": "客队",
        "sellStatus": "1",
        "oddsList": [{"poolCode": "HAD", "h": 2.0, "d": 3.0, "a": 4.0}],
        "poolList": [
            {"poolCode": "HAD", "poolStatus": "Selling", "cbtSingle": 1, "cbtAllUp": 1},
            {"poolCode": "HHAD", "poolStatus": "Selling", "cbtAllUp": 1},
            {"poolCode": "CRS", "poolStatus": "Stopped", "cbtSingle": 0, "cbtAllUp": 0},
            {"poolCode": "TTG", "poolStatus": "Selling", "cbtAllUp": 1},
            {"poolCode": "HAFU", "poolStatus": "Selling", "cbtAllUp": 1},
        ],
    }
    raw = {
        "value": {"matchInfoList": [{"businessDate": "2026-07-13", "subMatchList": [sub_match]}]}
    }

    markets = parse_matches_from_response(raw, "2026-07-13")[0]["_markets"]
    by_play = {market["play_type"]: market for market in markets}

    assert set(by_play) == {"spf", "rqspf", "bf", "zjq", "bqc"}
    assert by_play["spf"]["is_open"] is True
    assert by_play["spf"]["is_single_allowed"] is True
    assert by_play["spf"]["is_pass_allowed"] is True
    assert by_play["bf"]["is_open"] is False
    assert by_play["bf"]["market_status"] == "stopped"


def test_match_calculator_payload_parses_all_five_play_odds():
    sub_match = {
        "matchNumStr": "周一203",
        "matchDate": "2026-07-14",
        "matchTime": "03:00",
        "leagueAllName": "测试联赛",
        "homeTeamAllName": "主队",
        "awayTeamAllName": "客队",
        "poolList": [
            {"poolCode": code, "poolStatus": "Selling", "cbtSingle": 1, "cbtAllUp": 1}
            for code in ("HAD", "HHAD", "CRS", "TTG", "HAFU")
        ],
        "had": {"h": "2.10", "d": "3.20", "a": "3.40"},
        "hhad": {"goalLine": "-1", "h": "4.20", "d": "3.60", "a": "1.62"},
        "crs": {"s01s00": "7.50", "s1sh": "20.00", "s01s00f": "0"},
        "ttg": {"s0": "12.00", "s7": "15.00", "s0f": "0"},
        "hafu": {"hh": "3.20", "da": "18.00", "hhf": "0"},
    }

    snapshots = parse_odds_snapshots_from_match(sub_match, "2026-07-13T12:00:00")

    assert {snapshot["play_type"] for snapshot in snapshots} == {"spf", "rqspf", "bf", "zjq", "bqc"}
    assert len(snapshots) == 12
    assert (
        next(
            item
            for item in snapshots
            if item["play_type"] == "rqspf" and item["option_code"] == "h"
        )["handicap"]
        == -1.0
    )
    assert (
        next(
            item for item in snapshots if item["play_type"] == "bf" and item["option_code"] == "1:0"
        )["option_name"]
        == "1:0"
    )
    assert (
        next(
            item
            for item in snapshots
            if item["play_type"] == "bf" and item["option_code"] == "other_h"
        )["option_name"]
        == "胜其他"
    )
    assert {item["option_code"] for item in snapshots if item["play_type"] == "zjq"} == {"0", "7"}
    assert {item["option_code"] for item in snapshots if item["play_type"] == "bqc"} == {"33", "10"}
    assert all(item["is_single_allowed"] is True for item in snapshots)
    assert all(item["is_pass_allowed"] is True for item in snapshots)


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
    raw = {
        "value": {"matchInfoList": [{"businessDate": "2026-07-13", "subMatchList": [sub_match]}]}
    }

    match = parse_matches_from_response(raw, "2026-07-13")[0]
    snapshots = parse_odds_snapshots_from_match(sub_match, "2026-07-13T12:00:00")

    assert [market["play_type"] for market in match["_markets"]] == ["spf"]
    assert {snapshot["play_type"] for snapshot in snapshots} == {"spf"}
    assert all(snapshot["is_single_allowed"] is False for snapshot in snapshots)
    assert all(snapshot["is_pass_allowed"] is False for snapshot in snapshots)


def test_blocked_official_results_are_reported_without_third_party_fallback():
    client = MagicMock()
    client.get_uniform_match_results.side_effect = RuntimeError("403 Forbidden")
    connection = MagicMock()

    with (
        patch("scripts.official_crawler.SportteryClient", return_value=client),
        patch("scripts.official_crawler.get_db") as get_db,
        patch("scripts.official_crawler.record_official_collection_status") as record_status,
        patch("scripts.official_crawler.log_crawl"),
        patch("scripts.official_crawler.update_health") as update_health,
    ):
        get_db.return_value.__enter__.return_value = connection

        result = crawl_official_results("2026-07-10", "2026-07-11")

    assert result["status"] == "error"
    assert result["source"] == "sporttery"
    assert "403" in result["error"]
    record_status.assert_called_once()
    update_health.assert_called_once()


def test_parse_uniform_official_result_uses_source_id_and_confirmed_status():
    raw = {
        "value": {
            "matchResult": [
                {
                    "matchId": 2040511,
                    "matchNumStr": "周二201",
                    "matchDate": "2026-07-15",
                    "sectionsNo1": "1:1",
                    "sectionsNo999": "2:2",
                    "goalLine": "-1",
                    "matchResultStatus": "2",
                    "poolStatus": "Payout",
                }
            ]
        }
    }

    result = parse_results_from_response(raw)[0]

    assert result["_source_match_id"] == "2040511"
    assert result["_match_date"] == "2026-07-15"
    assert result["result_status"] == "confirmed"
    assert result["spf_result"] == "1"
    assert result["rqspf_result"] == "0"


def test_parse_official_refund_result_as_void_even_when_result_status_is_confirmed():
    raw = {
        "value": {
            "matchResult": [
                {
                    "matchId": 2040512,
                    "matchNumStr": "周四208",
                    "matchDate": "2026-07-16",
                    "sectionsNo999": "无效场次",
                    "matchResultStatus": "2",
                    "poolStatus": "Refund",
                }
            ]
        }
    }

    result = parse_results_from_response(raw)[0]

    assert result["result_status"] == "void"
    assert result["spf_result"] is None


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


def test_legacy_odds_snapshot_entrypoint_uses_durable_dispatcher():
    expected = {"status": "ok", "matches_due": 1, "snapshots_inserted": 54}

    with patch(
        "scripts.official_odds_capture.collect_due_official_odds", return_value=expected
    ) as collect:
        result = crawl_official_odds_snapshot("2026-07-10")

    assert result == expected
    collect.assert_called_once_with()


def test_schedule_refresh_updates_metadata_without_writing_odds_snapshots():
    client = MagicMock()
    client.get_uniform_match_list.return_value = {"value": {"matchInfoList": []}}
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (12,)
    matches = [
        {
            "official_match_code": "周五098",
            "business_date": "2026-07-10",
            "_markets": [{"play_type": "spf", "is_open": True}],
            "raw_json": {"matchId": "2040466"},
        }
    ]

    with (
        patch("scripts.official_crawler.SportteryClient", return_value=client),
        patch("scripts.official_crawler.parse_matches_from_response", return_value=matches),
        patch("scripts.official_crawler.get_db") as get_db,
        patch("scripts.official_crawler.store_matches", return_value={"inserted": 1, "updated": 0}),
        patch("scripts.official_crawler.store_markets") as store_markets,
        patch("scripts.official_crawler.parse_odds_snapshots_from_match") as parse_odds,
        patch("scripts.official_crawler.log_crawl"),
        patch("scripts.official_crawler.update_health") as update_health,
    ):
        get_db.return_value.__enter__.return_value = connection

        result = crawl_official_schedule_v2("2026-07-10")

    assert result["status"] == "ok"
    assert result["snapshots_inserted"] == 0
    store_markets.assert_called_once_with(connection, 12, matches[0]["_markets"])
    parse_odds.assert_not_called()
    update_health.assert_called_once_with(connection, "sporttery_v2", "schedule", "ok", ANY)
