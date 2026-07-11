from unittest.mock import ANY, MagicMock, patch

from scripts.official_crawler import crawl_official_results, parse_matches_from_response


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
