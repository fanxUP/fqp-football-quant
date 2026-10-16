from datetime import datetime
from unittest.mock import patch

import pytest

from apps.backend.src.routers import dashboard


def test_dashboard_metadata_uses_business_timezone(monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "business_now",
        lambda: datetime.fromisoformat("2026-07-18T13:30:00+08:00"),
    )

    assert dashboard._meta("view") == {
        "updated_at": "2026-07-18T13:30:00+08:00",
        "source": "view",
    }


@pytest.mark.parametrize("total", [0, 12_556_119])
def test_prediction_count_is_exact_and_does_not_load_prediction_details(client, mock_conn, total):
    conn, cur = mock_conn
    cur.fetchone.return_value = (total,)
    with patch.object(dashboard, "get_db") as get_db:
        get_db.return_value.__enter__.return_value = conn
        response = client.get("/api/dashboard/prediction-count")
    assert response.status_code == 200
    assert response.json() == {"total": total}
    cur.execute.assert_called_once()
    sql = " ".join(cur.execute.call_args.args[0].split())
    assert "COUNT(*)" in sql
    assert "JOIN model_versions mv ON mv.id = mp.model_version_id" in sql
    assert "JOIN official_matches m ON m.id = mp.match_id" in sql
    assert "mp.validation_status = 'valid'" in sql
    assert "mp.predict_time < m.kickoff_time" in sql
    for unnecessary in [
        "DISTINCT",
        "ORDER BY",
        "AVG(",
        "mp.ev",
        "mp.confidence_score",
        "LIMIT",
        "is_active",
        "feature_snapshots",
    ]:
        assert unnecessary not in sql
    cur.fetchall.assert_not_called()


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
def test_prediction_count_requires_authentication(client, monkeypatch, prefix):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with patch.object(dashboard, "get_db") as get_db:
        response = client.get(f"{prefix}/dashboard/prediction-count")
    assert response.status_code == 401
    get_db.assert_not_called()


def test_prediction_count_does_not_turn_database_failure_into_zero(client):
    with patch.object(dashboard, "get_db", side_effect=RuntimeError("database unavailable")):
        with pytest.raises(RuntimeError, match="database unavailable"):
            client.get("/api/dashboard/prediction-count")
