import json

from scripts.official_history_importer import (
    extract_official_result_payloads,
    parse_local_official_results_text,
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
