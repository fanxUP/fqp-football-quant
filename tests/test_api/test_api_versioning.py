"""API version compatibility tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_api_v1_routes_to_existing_api_handlers(client):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
        resp = client.get("/api/v1/predictions?limit=10")

    assert resp.status_code == 200
    assert resp.json() == {"predictions": [], "total": 0}
