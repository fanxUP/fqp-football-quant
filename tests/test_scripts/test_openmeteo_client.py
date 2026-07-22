from unittest.mock import MagicMock, patch

from scripts.openmeteo_client import OpenMeteoClient


def test_requests_reuse_the_long_lived_http_client_connection():
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"latitude": 1.0, "longitude": 2.0}

    with (
        patch("scripts.openmeteo_client.httpx.Client") as client_class,
        patch("scripts.openmeteo_client.httpx.get") as one_shot_get,
    ):
        client_class.return_value.get.return_value = response
        client = OpenMeteoClient(min_interval=0)

        result = client._request("forecast", {"latitude": 1.0, "longitude": 2.0})

    assert result["latitude"] == 1.0
    client_class.return_value.get.assert_called_once()
    one_shot_get.assert_not_called()
