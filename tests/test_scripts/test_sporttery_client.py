from unittest.mock import MagicMock

from scripts.sporttery_client import SportteryClient


def test_uniform_match_calculator_uses_official_odds_endpoint_and_same_origin_referer():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(return_value={"errorCode": "0", "value": {}})

    try:
        result = client.get_uniform_match_calculator()
    finally:
        client.close()

    assert result["errorCode"] == "0"
    client._request_url.assert_called_once_with(
        "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry",
        {"channel": "c"},
        referer="https://www.sporttery.cn/jc/jsq/zqspf/",
    )


def test_uniform_match_list_uses_official_schedule_referer():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(return_value={"errorCode": "0", "value": {}})

    try:
        result = client.get_uniform_match_list()
    finally:
        client.close()

    assert result["errorCode"] == "0"
    client._request_url.assert_called_once_with(
        "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry",
        {"clientCode": "3001"},
        referer="https://www.sporttery.cn/jc/zqszsc/",
    )


def test_uniform_match_results_reuses_odds_client_and_fetches_one_day_at_a_time():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(
        side_effect=[
            {
                "errorCode": "0",
                "value": {"pages": 1, "matchResult": [{"matchId": 101}]},
            },
            {
                "errorCode": "0",
                "value": {"pages": 1, "matchResult": [{"matchId": 102}]},
            },
        ]
    )

    try:
        result = client.get_uniform_match_results("2026-07-14", "2026-07-15")
    finally:
        client.close()

    assert [row["matchId"] for row in result["value"]["matchResult"]] == [101, 102]
    assert client._request_url.call_count == 2
    first_call = client._request_url.call_args_list[0]
    assert first_call.args[0].endswith("getUniformMatchResultV1.qry")
    assert first_call.args[1]["matchBeginDate"] == "2026-07-14"
    assert first_call.args[1]["matchEndDate"] == "2026-07-14"
    assert first_call.kwargs["referer"] == "https://www.lottery.gov.cn/jc/zqsgkj/"


def test_uniform_league_catalog_uses_official_league_referer():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(return_value={"errorCode": "0", "value": {}})

    try:
        result = client.get_uniform_league_list()
    finally:
        client.close()

    assert result["errorCode"] == "0"
    client._request_url.assert_called_once_with(
        "https://webapi.sporttery.cn/gateway/uniform/football/league/getLeagueListV1.qry",
        referer="https://www.sporttery.cn/zqlszl/",
    )


def test_uniform_league_matches_passes_official_season_window_parameters():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(return_value={"errorCode": "0", "value": {}})

    try:
        result = client.get_uniform_league_matches(
            uniform_league_id=1085,
            season_id=14355,
            start_date="2026-04-04",
            end_date="2026-04-10",
        )
    finally:
        client.close()

    assert result["errorCode"] == "0"
    client._request_url.assert_called_once_with(
        "https://webapi.sporttery.cn/gateway/uniform/football/league/getMatchResultV1.qry",
        {
            "uniformLeagueId": 1085,
            "seasonId": 14355,
            "startDate": "2026-04-04",
            "endDate": "2026-04-10",
        },
        referer="https://www.sporttery.cn/zqlszl/",
    )


def test_uniform_match_calculator_rejects_official_api_error_payload():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(
        return_value={"errorCode": "1001", "errorMessage": "invalid channel"}
    )

    try:
        try:
            client.get_uniform_match_calculator()
        except RuntimeError as exc:
            assert "invalid channel" in str(exc)
        else:
            raise AssertionError(
                "official API error payload must not be treated as a successful empty response"
            )
    finally:
        client.close()
