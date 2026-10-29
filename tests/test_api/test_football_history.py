"""Single-match historical references keep normal auth and bounded reads."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2.errors import QueryCanceled, UndefinedTable

from apps.backend.src.app import create_app


@pytest.mark.parametrize(
    "path",
    [
        "/api/matches/0/history-reference",
        "/api/matches/9007199254740992/history-reference",
        "/api/matches/1/history-reference?limit=101",
        "/api/matches/1/history-reference?offset=-1",
        "/api/matches/1/history-reference?offset=10001",
        "/api/matches/1/history-reference?batch_id=0",
        "/api/matches/1/history-reference?domain=player_transfers",
    ],
)
def test_invalid_history_query_does_not_reach_database(client, path):
    with patch("apps.backend.src.routers.football_history.get_db") as get_db:
        assert client.get(path).status_code == 422
    get_db.assert_not_called()


def test_history_requires_session(monkeypatch):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with patch("apps.backend.src.routers.football_history.get_db") as get_db:
        assert TestClient(create_app()).get("/api/matches/1/history-reference").status_code == 401
    get_db.assert_not_called()


def test_pinned_batch_and_page_are_forwarded(client):
    with (
        patch("apps.backend.src.routers.football_history.get_db"),
        patch("apps.backend.src.routers.football_history.match_history_reference") as read,
    ):
        read.return_value = {"status": "available", "match_id": 7}
        response = client.get(
            "/api/matches/7/history-reference?domain=odds_history&batch_id=3&limit=20&offset=40"
        )
    assert response.status_code == 200
    assert read.call_args.kwargs == {
        "domain": "odds_history",
        "batch_id": 3,
        "limit": 20,
        "offset": 40,
    }
    assert read.call_args.args[1] == 7


@pytest.mark.parametrize("error", [UndefinedTable(), QueryCanceled()])
def test_unready_or_timed_out_history_is_retryable(client, error):
    with (
        patch("apps.backend.src.routers.football_history.get_db"),
        patch(
            "apps.backend.src.routers.football_history.match_history_reference", side_effect=error
        ),
    ):
        assert client.get("/api/matches/1/history-reference").status_code == 503


def test_unknown_match_or_pinned_batch_is_not_silently_replaced(client):
    with (
        patch("apps.backend.src.routers.football_history.get_db"),
        patch(
            "apps.backend.src.routers.football_history.match_history_reference",
            side_effect=LookupError("所选比赛或批次不存在"),
        ),
    ):
        assert client.get("/api/matches/1/history-reference?batch_id=999").status_code == 404
