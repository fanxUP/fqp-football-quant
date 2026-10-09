from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from apps.backend.src.services.execution_evidence import get_execution_detail, project_refs


def test_reference_projection_never_exports_arbitrary_strings():
    refs = project_refs(
        {
            "dependencies": ["official_odds_snapshot", "https://secret/token", "x" * 200],
            "match_id": 18,
            "model_version_id": 4,
            "feature_snapshot_ids": [1, 2, True, -9],
            "api_key": "secret",
            "result": {"predictions": 0, "prompt": "secret", "error": "secret"},
        }
    )
    assert refs == {
        "dependencies": ["official_odds_snapshot"],
        "match_id": 18,
        "model_version_id": 4,
        "feature_snapshot_ids": [1, 2],
        "result": {"predictions": 0},
    }
    assert "secret" not in str(refs)


@pytest.mark.parametrize("value", [None, "secret", [], {"api_key": "secret"}])
def test_empty_or_unstructured_refs_are_not_exported(value):
    assert project_refs(value) == {}


def test_refs_have_strict_numeric_types_and_bounds():
    assert project_refs(
        {
            "match_id": True,
            "snapshot_id": -1,
            "model_version_id": 0,
            "predictions": 0,
            "count": float("inf"),
            "dependencies": ["x"] * 500,
        }
    ) == {"predictions": 0, "dependencies": ["x"]}


def test_detail_is_read_only_parameterized_and_hides_error(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (
        9,
        "model_prediction",
        "模型预测",
        "model_agent",
        "scheduled",
        "local",
        "failed",
        0,
        datetime(2026, 10, 8, 1),
        None,
        None,
        "Bearer secret https://user:password@host",
        {"match_id": 3, "api_key": "secret"},
        {"result": {"predictions": 0, "trace": "secret"}},
    )
    detail = get_execution_detail(conn, 9)
    sql, params = cur.execute.call_args.args
    assert "WHERE id = %s" in sql
    assert params == (9,)
    conn.commit.assert_not_called()
    assert detail["id"] == 9
    assert detail["started_at"] == "2026-10-08T01:00:00Z"
    assert detail["has_error"] is True
    assert "secret" not in str(detail)
    assert detail["input_refs"] == {"match_id": 3}
    assert detail["output_refs"] == {"result": {"predictions": 0}}


def test_missing_detail_returns_none(mock_conn):
    conn, _ = mock_conn
    assert get_execution_detail(conn, 99) is None


def test_detail_route_returns_404_and_rejects_invalid_ids(client):
    with (
        patch("apps.backend.src.routers.agents.get_db", return_value=MagicMock()),
        patch("apps.backend.src.routers.agents._execution_detail", return_value=None),
    ):
        assert client.get("/api/ai-jobs/99").status_code == 404
        assert client.get("/api/ai-jobs/0").status_code == 422
        assert client.get("/api/ai-jobs/99999999999999999999999").status_code == 422
        assert client.get("/api/ai-jobs/nope").status_code == 422


def test_overview_route_limit_validation_and_metadata(client):
    overview = {"agents": [], "jobs": [], "tasks": [], "observed_at": "2026-10-08T00:00:00Z"}
    with (
        patch("apps.backend.src.routers.agents.get_db", return_value=MagicMock()),
        patch(
            "apps.backend.src.routers.agents._execution_overview", return_value=overview
        ) as query,
    ):
        response = client.get("/api/agent-execution-overview?limit=100")
        assert response.status_code == 200
        assert response.json()["limit"] == 100
        assert response.json()["observed_at"] == overview["observed_at"]
        assert client.get("/api/agent-execution-overview?limit=201").status_code == 422
        assert client.get("/api/agent-execution-overview?limit=0").status_code == 422
        assert query.call_count == 1


@pytest.mark.parametrize("path", ["/api/agent-execution-overview", "/api/ai-jobs/9"])
def test_new_routes_require_authentication(monkeypatch, path):
    from fastapi.testclient import TestClient

    from apps.backend.src.app import create_app

    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with TestClient(create_app()) as authenticated_client:
        assert authenticated_client.get(path).status_code == 401


def test_overview_drops_raw_logs_and_payloads():
    from apps.backend.src.services.execution_evidence import get_execution_overview

    row = {
        "id": 1,
        "job_code": "model_prediction",
        "job_name": "模型预测",
        "owner_agent": "model_agent",
        "status": "running",
        "started_at": None,
        "finished_at": None,
        "retry_count": 0,
        "error_message": "secret",
        "input_refs": {"api_key": "secret"},
    }
    with (
        patch("apps.backend.src.services.execution_evidence.list_agents", return_value=[]),
        patch("apps.backend.src.services.execution_evidence.list_agent_tasks", return_value=[]),
        patch("apps.backend.src.services.execution_evidence.list_job_runs", return_value=[row]),
        patch(
            "apps.backend.src.services.execution_evidence.get_scheduler_status",
            return_value={"running": False, "pid": "secret"},
        ),
    ):
        data = get_execution_overview(MagicMock(), limit=100)
    assert data["jobs"][0]["status"] == "running"
    assert "secret" not in str(data)
    assert data["scheduler"] == {"running": False, "heartbeat_at": None}


def test_unbounded_numbers_and_nested_payloads_are_not_exported():
    assert project_refs({"match_id": 10**500, "result": {"result": {"predictions": 5}}}) == {}
