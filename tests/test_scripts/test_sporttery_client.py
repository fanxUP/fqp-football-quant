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


def test_uniform_match_calculator_rejects_official_api_error_payload():
    client = SportteryClient(min_interval=0)
    client._request_url = MagicMock(return_value={"errorCode": "1001", "errorMessage": "invalid channel"})

    try:
        try:
            client.get_uniform_match_calculator()
        except RuntimeError as exc:
            assert "invalid channel" in str(exc)
        else:
            raise AssertionError("official API error payload must not be treated as a successful empty response")
    finally:
        client.close()
