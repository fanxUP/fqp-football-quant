"""Read-only research evidence must refer to the recorded prediction, not latest state."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize("query", ["", "?match_id=101&limit=200"])
def test_prediction_research_uses_exact_foreign_keys(client, query):
    now = datetime(2026, 10, 9, 9)
    row = (
        1,
        101,
        now,
        "elo_rating",
        "spf",
        "3",
        0,
        0,
        None,
        None,
        -1,
        0,
        "甲",
        "乙",
        9,
        "1.0",
        "statistical",
        "features-v1",
        81,
        now,
        "v1",
        {"rest": True, "lineup": False},
        91,
        now,
    )
    conn = MagicMock()
    cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [row]
    cur.fetchone.return_value = (1, 0, 0, 1, now)
    with patch("apps.backend.src.routers.predictions.get_db", return_value=conn):
        result = client.get("/api/predictions" + query)
    assert result.status_code == 200
    evidence = result.json()["predictions"][0]["research_evidence"]
    assert evidence["model_version_id"] == 9
    assert evidence["model_version"] == "1.0"
    assert evidence["model_type"] == "statistical"
    assert evidence["feature_set_version"] == "features-v1"
    assert evidence["feature_snapshot_id"] == 81
    assert evidence["feature_categories"] == ["rest"]
    assert evidence["odds_snapshot_id"] == 91
    assert result.json()["predictions"][0]["model_probability"] == 0
    sql = cur.execute.call_args_list[0].args[0]
    for fragment in [
        "fs.id = mp.feature_snapshot_id",
        "fs.match_id = mp.match_id",
        "fs.snapshot_time <= mp.predict_time",
        "od.id = mp.odds_snapshot_id",
        "od.match_id = mp.match_id",
        "od.play_type = mp.play_type",
        "od.snapshot_time <= mp.predict_time",
        "CASE mp.option_code",
    ]:
        assert fragment in sql
    assert "recent AS MATERIALIZED" in sql
    assert "LIMIT %(limit)s" in sql.split("FROM recent mp")[0]
    assert cur.execute.call_args_list[0].args[1] == {
        "match_id": 101 if query else None,
        "limit": 200 if query else 20,
    }
    assert "mp.play_type IN ('spf', 'rqspf')" in sql
    assert "parameters_json" not in sql
    assert "raw_feature_refs" not in sql


def test_missing_research_evidence_is_not_inferred(client):
    now = datetime(2026, 10, 9, 9)
    row = (
        1,
        101,
        now,
        "elo_rating",
        "spf",
        "3",
        None,
        None,
        None,
        None,
        None,
        None,
        "甲",
        "乙",
        9,
        "1.0",
        "statistical",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    conn = MagicMock()
    cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [row]
    cur.fetchone.return_value = (1, 0, None, 1, now)
    with patch("apps.backend.src.routers.predictions.get_db", return_value=conn):
        result = client.get("/api/predictions")
    evidence = result.json()["predictions"][0]["research_evidence"]
    assert evidence["feature_snapshot_id"] is None
    assert evidence["odds_snapshot_id"] is None
    assert evidence["feature_categories"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "match_id=-1"])
def test_research_read_parameters_are_bounded(client, query):
    with patch("apps.backend.src.routers.predictions.get_db") as get_db:
        response = client.get("/api/predictions?" + query)
    assert response.status_code == 422
    get_db.assert_not_called()


def test_research_route_stays_protected(monkeypatch):
    from fastapi.testclient import TestClient

    from apps.backend.src.app import create_app

    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with patch("apps.backend.src.routers.predictions.get_db") as get_db:
        response = TestClient(create_app()).get("/api/predictions?limit=200")
    assert response.status_code == 401
    get_db.assert_not_called()


@pytest.mark.parametrize("path", ["/api/predictions", "/api/models/predictions"])
def test_records_only_read_skips_full_aggregate(client, path):
    conn = MagicMock()
    cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    with patch("apps.backend.src.routers.predictions.get_db", return_value=conn):
        response = client.get(path + "?limit=200&include_summary=false")
    assert response.status_code == 200
    assert response.json() == {"predictions": [], "total": None, "summary": None}
    assert cur.execute.call_count == 1
    assert "recent AS MATERIALIZED" in cur.execute.call_args.args[0]
    assert cur.execute.call_args.args[1] == {"match_id": None, "limit": 200}
    cur.fetchone.assert_not_called()


def test_records_only_parameter_rejects_invalid_boolean(client):
    with patch("apps.backend.src.routers.predictions.get_db") as get_db:
        response = client.get("/api/predictions?include_summary=banana")
    assert response.status_code == 422
    get_db.assert_not_called()
