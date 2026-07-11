from unittest.mock import MagicMock, patch


def test_review_gates_endpoint_returns_gate_context(client):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    gates = [{
        "id": 1,
        "task_code": "RISK-001",
        "task_title": "推荐审核",
        "review_status": "pending",
    }]
    with patch("apps.backend.src.routers.agents.get_db", return_value=mock_conn), \
         patch("apps.backend.src.routers.agents._list_gates", return_value=gates):
        resp = client.get("/api/agent-review-gates?review_status=pending&limit=10")

    assert resp.status_code == 200
    assert resp.json() == {"gates": gates, "total": 1}


def test_agent_summary_endpoint_returns_counts(client):
    summary = {
        "active_agents": 11,
        "open_tasks": 2,
        "running_jobs": 1,
        "stale_jobs": 0,
        "failed_jobs_24h": 0,
        "pending_review_gates": 1,
        "scheduler_running": True,
    }
    mock_conn = MagicMock()
    with patch("apps.backend.src.routers.agents.get_db", return_value=mock_conn), \
         patch("apps.backend.src.routers.agents._get_summary", return_value=summary):
        resp = client.get("/api/agent-summary")
    assert resp.status_code == 200
    assert resp.json() == {"summary": summary}


def test_review_gate_resolve_requires_explicit_reviewer(client):
    resp = client.post("/api/agent-review-gates/1/resolve", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_review_gate_resolve_updates_gate(client):
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    with patch("apps.backend.src.routers.agents.get_db", return_value=mock_conn), \
         patch("apps.backend.src.routers.agents._resolve_gate", return_value=True) as resolve:
        resp = client.post(
            "/api/agent-review-gates/1/resolve",
            json={"reviewer": "human", "status": "approved", "comment": "checked"},
        )
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "approved"
    resolve.assert_called_once_with(mock_conn, 1, "human", "approved", "checked")


def test_stale_jobs_endpoint_returns_diagnostics(client):
    jobs = [{"id": 4, "job_code": "weather_collection", "running_minutes": 42.5}]
    mock_conn = MagicMock()
    with patch("apps.backend.src.routers.agents.get_db", return_value=mock_conn), \
         patch("apps.backend.src.routers.agents._list_stale_jobs", return_value=jobs):
        resp = client.get("/api/agent-stale-jobs?threshold_minutes=30")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": jobs, "total": 1, "threshold_minutes": 30}


def test_scheduler_status_endpoint_returns_diagnostics(client):
    status = {"running": False, "heartbeat_at": None, "pid": None, "pid_alive": False}
    with patch("apps.backend.src.routers.agents.get_scheduler_status", return_value=status):
        resp = client.get("/api/agent-scheduler-status")
    assert resp.status_code == 200
    assert resp.json() == {"scheduler": status}
