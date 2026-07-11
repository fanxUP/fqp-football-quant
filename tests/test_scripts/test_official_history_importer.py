import json
from unittest.mock import MagicMock

from scripts.official_history_importer import (
    extract_official_result_payloads,
    parse_local_official_history_text,
    parse_local_official_results_text,
    resolve_official_match_id,
)


def test_extracts_result_payload_from_har_entry():
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchResultV1.qry"
                    },
                    "response": {
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "value": {
                                        "matchResultList": [
                                            {
                                                "matchNum": "周五001",
                                                "fullHomeGoals": 2,
                                                "fullAwayGoals": 1,
                                            }
                                        ]
                                    }
                                },
                                ensure_ascii=False,
                            ),
                        }
                    },
                }
            ]
        }
    }

    payloads = extract_official_result_payloads(json.dumps(har, ensure_ascii=False))

    assert len(payloads) == 1
    assert payloads[0]["value"]["matchResultList"][0]["matchNum"] == "周五001"


def test_parses_embedded_html_result_payload_into_normalized_results():
    html = """
    <html><body>
    <script>
      window.__SPORTTERY_RESULTS__ = {
        "value": {
          "matchResultList": [{
            "matchNum": "周六002",
            "halfHomeGoals": "1",
            "halfAwayGoals": "0",
            "fullHomeGoals": "3",
            "fullAwayGoals": "1",
            "resultStatus": "confirmed"
          }]
        }
      };
    </script>
    </body></html>
    """

    results = parse_local_official_results_text(
        html,
        source_path="/tmp/sporttery-result.html",
    )

    assert len(results) == 1
    assert results[0]["_match_code"] == "周六002"
    assert results[0]["spf_result"] == "3"
    assert results[0]["score_result"] == "3:1"
    assert results[0]["raw_json"]["_source_artifact"]["path"] == "/tmp/sporttery-result.html"
    assert results[0]["raw_json"]["_source_artifact"]["hash"]


def test_parses_official_history_match_with_date_code_and_source_id():
    payload = {
        "value": {
            "matchResultList": [
                {
                    "matchId": 2040374,
                    "businessDate": "2026-07-10",
                    "matchNumStr": "周五098",
                    "matchDate": "2026-07-11",
                    "matchTime": "03:00",
                    "leagueAllName": "世界杯",
                    "homeTeamAllName": "西班牙",
                    "awayTeamAllName": "比利时",
                    "fullHomeGoals": 2,
                    "fullAwayGoals": 1,
                    "resultStatus": "confirmed",
                }
            ]
        }
    }

    history = parse_local_official_history_text(
        json.dumps(payload, ensure_ascii=False),
        source_path="/tmp/sporttery-history.json",
    )

    assert history["rejected"] == []
    assert history["matches"][0]["business_date"] == "2026-07-10"
    assert history["matches"][0]["official_match_code"] == "周五098"
    assert history["matches"][0]["source_match_id"] == "2040374"
    assert history["matches"][0]["kickoff_time"] == "2026-07-11T03:00"
    assert history["results"][0]["_business_date"] == "2026-07-10"
    assert history["results"][0]["_match_code"] == "周五098"
    assert history["results"][0]["_source_match_id"] == "2040374"


def test_rejects_history_row_when_display_code_weekday_disagrees_with_business_date():
    payload = {
        "value": {
            "matchResultList": [
                {
                    "matchId": 2040374,
                    "businessDate": "2026-07-10",
                    "matchNumStr": "周六098",
                    "matchDate": "2026-07-11",
                    "matchTime": "03:00",
                    "leagueAllName": "世界杯",
                    "homeTeamAllName": "西班牙",
                    "awayTeamAllName": "比利时",
                    "fullHomeGoals": 2,
                    "fullAwayGoals": 1,
                }
            ]
        }
    }

    history = parse_local_official_history_text(
        json.dumps(payload, ensure_ascii=False),
        source_path="/tmp/sporttery-history.json",
    )

    assert history["matches"] == []
    assert history["results"] == []
    assert history["rejected"] == [
        {
            "business_date": "2026-07-10",
            "official_match_code": "周六098",
            "reason": "match code weekday does not match business_date",
        }
    ]


def test_does_not_invent_business_date_for_multi_day_artifact():
    payload = {
        "value": {
            "matchResultList": [
                {
                    "matchId": 2040374,
                    "matchNumStr": "周五098",
                    "matchDate": "2026-07-11",
                    "matchTime": "03:00",
                    "leagueAllName": "世界杯",
                    "homeTeamAllName": "西班牙",
                    "awayTeamAllName": "比利时",
                    "fullHomeGoals": 2,
                    "fullAwayGoals": 1,
                }
            ]
        }
    }

    history = parse_local_official_history_text(
        json.dumps(payload, ensure_ascii=False),
        source_path="/tmp/sporttery-history.json",
    )

    assert history["matches"] == []
    assert history["results"] == []
    assert history["rejected"][0]["reason"] == "missing official business_date"


def test_resolves_history_result_by_sporttery_source_id_first():
    cursor = MagicMock()
    cursor.fetchone.return_value = (42,)

    match_id = resolve_official_match_id(
        cursor,
        source_match_id="2040374",
        business_date="2026-07-10",
        match_code="周五098",
    )

    assert match_id == 42
    sql, params = cursor.execute.call_args.args
    assert "source_match_id = %s" in sql
    assert params == ("2040374",)


def test_resolves_history_result_by_exact_business_date_and_display_code_only():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, (84,)]

    match_id = resolve_official_match_id(
        cursor,
        source_match_id="2040374",
        business_date="2026-07-10",
        match_code="周五098",
    )

    assert match_id == 84
    sql, params = cursor.execute.call_args_list[1].args
    assert "business_date = %s" in sql
    assert "official_match_code = %s" in sql
    assert "ORDER BY business_date DESC" not in sql
    assert params == ("2026-07-10", "周五098")


def test_missing_code_row_cannot_shift_the_next_official_result_identity():
    payload = {
        "value": {
            "matchResultList": [
                {
                    "businessDate": "2026-07-10",
                    "fullHomeGoals": 9,
                    "fullAwayGoals": 9,
                },
                {
                    "matchId": 2040374,
                    "businessDate": "2026-07-10",
                    "matchNumStr": "周五098",
                    "matchDate": "2026-07-11",
                    "matchTime": "03:00",
                    "leagueAllName": "世界杯",
                    "homeTeamAllName": "西班牙",
                    "awayTeamAllName": "比利时",
                    "fullHomeGoals": 2,
                    "fullAwayGoals": 1,
                },
            ]
        }
    }

    history = parse_local_official_history_text(
        json.dumps(payload, ensure_ascii=False),
        source_path="/tmp/sporttery-history.json",
    )

    assert history["rejected"][0]["reason"] == "missing or invalid official display match code"
    assert history["results"][0]["_match_code"] == "周五098"
    assert history["results"][0]["score_result"] == "2:1"
