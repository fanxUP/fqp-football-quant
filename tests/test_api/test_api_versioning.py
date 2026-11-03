"""API version compatibility tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_api_v1_routes_to_existing_api_handlers(client):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []
    summary = {
        "total": 0,
        "positive_ev_count": 0,
        "avg_confidence": None,
        "model_count": 0,
        "latest_predict_time": None,
    }
    meta = {
        "status": "ok",
        "data_as_of": "2026-10-09T09:00:00+00:00",
        "last_success_at": "2026-10-09T09:00:00+00:00",
        "last_attempt_at": None,
        "age_seconds": 0,
        "stale_after_seconds": 2700,
        "is_stale": False,
    }

    with (
        patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn),
        patch(
            "apps.backend.src.routers.predictions.get_prediction_summary_snapshot",
            return_value={"summary": summary, "meta": meta},
        ),
    ):
        resp = client.get("/api/v1/predictions?limit=10")

    assert resp.status_code == 200
    assert resp.json() == {
        "predictions": [],
        "total": 0,
        "summary": summary,
        "summary_meta": meta,
    }
