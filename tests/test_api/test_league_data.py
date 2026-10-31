"""The league read boundary validates inputs and keeps ordinary session auth."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.backend.src.app import create_app


@pytest.mark.parametrize(
    "path",
    [
        "/api/league-data/seasons/0",
        "/api/league-data/catalog?dataset=bad",
        "/api/league-data/seasons/1?dataset=bad",
        "/api/league-data/seasons/1/fixtures?dataset=verified&batch_id=1",
        "/api/league-data/seasons/1/fixtures?dataset=verified&team_id=1",
        "/api/league-data/seasons/1/fixtures?dataset=verified&round_id=r1",
        "/api/league-data/seasons/9007199254740992",
        "/api/league-data/seasons/1/fixtures?limit=101",
        "/api/league-data/seasons/1/fixtures?offset=-1",
        "/api/league-data/seasons/1/fixtures?status=cancelled",
        "/api/league-data/seasons/1/fixtures?round_id=x%27",
        "/api/league-data/seasons/1/fixtures?batch_id=0",
    ],
)
def test_invalid_query_cannot_reach_database(client, path):
    with patch("apps.backend.src.routers.league_data.get_db") as get_db:
        assert client.get(path).status_code == 422
        get_db.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/api/league-data/catalog",
        "/api/league-data/catalog?dataset=verified",
        "/api/league-data/seasons/1?dataset=verified",
        "/api/league-data/seasons/1/fixtures?dataset=verified",
    ],
)
def test_reference_api_requires_session(monkeypatch, path):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with patch("apps.backend.src.routers.league_data.get_db") as get_db:
        response = TestClient(create_app()).get(path)
    assert response.status_code == 401
    get_db.assert_not_called()


def test_missing_season_returns_404_without_external_fallback(client):
    with (
        patch(
            "apps.backend.src.routers.league_data.league_season",
            side_effect=LookupError("所选赛季暂无覆盖"),
        ),
        patch("apps.backend.src.routers.league_data.get_db"),
    ):
        response = client.get("/api/league-data/seasons/123")
    assert response.status_code == 404
    assert response.json()["detail"] == "所选赛季暂无覆盖"


@pytest.mark.parametrize("error_name", ["QueryCanceled", "LockNotAvailable"])
def test_read_timeouts_return_retryable_503(client, error_name):
    import psycopg2.errors

    with (
        patch("apps.backend.src.routers.league_data.get_db"),
        patch(
            "apps.backend.src.routers.league_data.league_catalog",
            side_effect=getattr(psycopg2.errors, error_name)("bounded fixture timeout"),
        ),
    ):
        response = client.get("/api/league-data/catalog?dataset=verified")
    assert response.status_code == 503
    assert "超时" in response.json()["detail"]
