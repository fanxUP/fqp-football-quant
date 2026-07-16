"""Unit tests for agent_storage.py — agent registry, tasks, audit logs, job runs."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.agent_storage import (
    add_task_artifact,
    create_agent_task,
    create_review_gate,
    create_review_report,
    finish_job_run,
    get_agent,
    get_agent_summary,
    get_agent_task,
    list_agent_tasks,
    list_agents,
    list_audit_logs,
    list_job_runs,
    list_review_gates,
    list_stale_tasks,
    list_task_artifacts,
    recover_interrupted_job_runs,
    resolve_review_gate,
    retry_job_run,
    seed_agent_registry,
    start_job_run,
    transition_task,
    write_audit_log,
)


def _mock_conn(fetchone=None, fetchall=None, rowcount=1):
    """Create a mock connection with cursor."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = fetchone
    mock_cur.fetchall.return_value = fetchall if fetchall is not None else []
    mock_cur.rowcount = rowcount
    return mock_conn, mock_cur


class TestSeedAgentRegistry:
    def test_inserts_new_agents(self):
        agents = [
            {"name": "orchestrator", "type": "system", "description": "Main orchestrator"},
            {"name": "data_collector", "type": "worker", "description": "Collects data"},
        ]
        mock_conn, mock_cur = _mock_conn(rowcount=1)

        count = seed_agent_registry(mock_conn, agents)
        assert count == 2
        assert mock_cur.execute.call_count == 2
        mock_conn.commit.assert_called_once()

    def test_skips_existing_agents(self):
        agents = [{"name": "existing_agent", "type": "worker"}]
        mock_conn, mock_cur = _mock_conn(rowcount=0)  # ON CONFLICT DO NOTHING → 0 rows

        count = seed_agent_registry(mock_conn, agents)
        assert count == 0

    def test_uses_default_permission_level(self):
        agents = [{"name": "test_agent", "type": "worker"}]
        mock_conn, mock_cur = _mock_conn(rowcount=1)

        seed_agent_registry(mock_conn, agents)
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["permission_level"] == "P2"


class TestListAgents:
    def test_returns_formatted_agent_list(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, "agent_a", "system", "desc a", "P1", True, MagicMock(isoformat=lambda: "2025-01-01T00:00:00")),
        ])

        result = list_agents(mock_conn)
        assert len(result) == 1
        assert result[0]["agent_name"] == "agent_a"
        assert result[0]["is_active"] is True
        assert result[0]["created_at"] == "2025-01-01T00:00:00"

    def test_filters_inactive_agents(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_agents(mock_conn, is_active=False)
        assert result == []
        # Verify the query uses is_active=False
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["is_active"] is False


class TestGetAgent:
    def test_returns_agent_by_name(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1, "test_agent", "worker", "desc", "P2", True])

        result = get_agent(mock_conn, "test_agent")
        assert result is not None
        assert result["agent_name"] == "test_agent"
        assert result["agent_type"] == "worker"

    def test_returns_none_for_unknown_agent(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = get_agent(mock_conn, "nonexistent")
        assert result is None


class TestCreateAgentTask:
    def test_creates_task_and_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[10])

        task = {
            "task_code": "TASK-001",
            "task_title": "Test task",
            "owner_agent": "test_agent",
        }
        result = create_agent_task(mock_conn, task)
        assert result == 10
        mock_conn.commit.assert_called_once()

    def test_uses_defaults_for_missing_fields(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        task = {"task_code": "TASK-002"}
        result = create_agent_task(mock_conn, task)
        assert result == 1
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["priority"] == "medium"
        assert call_args["status"] == "created"
        assert call_args["human_review_required"] is False

    def test_json_serializes_input_refs(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        task = {"task_code": "TASK-003", "input_refs": {"snapshot_id": 42}}
        create_agent_task(mock_conn, task)
        call_args = mock_cur.execute.call_args[0][1]
        assert "snapshot_id" in call_args["input_refs"]


class TestTransitionTask:
    def test_updates_status_and_writes_audit(self):
        audit_row = [1]
        transition_row = [5]
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [transition_row, audit_row]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = transition_task(mock_conn, "TASK-001", "completed", "Done successfully")
        assert result is True
        assert mock_cur.execute.call_count == 2  # UPDATE + audit INSERT
        mock_conn.commit.assert_called()

    def test_returns_false_when_task_not_found(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = transition_task(mock_conn, "UNKNOWN", "completed")
        assert result is False

    def test_rejects_unknown_status(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[5])
        try:
            transition_task(mock_conn, "TASK-001", "not_a_status")
        except ValueError as exc:
            assert "Unsupported task status" in str(exc)
        else:
            raise AssertionError("expected ValueError")
        mock_cur.execute.assert_not_called()


class TestStaleAgentTasks:
    def test_summary_counts_stale_tasks_separately_from_jobs(self):
        mock_conn, mock_cur = _mock_conn()
        mock_cur.fetchone.side_effect = [
            [11], [2], [1], [3], [4], [0], [1],
        ]

        result = get_agent_summary(mock_conn)

        assert result["stale_jobs"] == 3
        assert result["stale_tasks"] == 4
        stale_task_query = mock_cur.execute.call_args_list[4].args[0]
        assert "FROM agent_tasks" in stale_task_query
        assert "running" in stale_task_query
        assert "in_progress" in stale_task_query

    def test_lists_active_tasks_older_than_threshold(self):
        started_at = MagicMock(isoformat=lambda: "2026-07-02T10:00:00")
        updated_at = MagicMock(isoformat=lambda: "2026-07-02T10:05:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (7, "TEST-001", "Test task", "qa_agent", "in_progress",
             started_at, updated_at, 20160.5),
        ])

        result = list_stale_tasks(mock_conn, threshold_minutes=60, limit=20)

        assert result == [{
            "id": 7,
            "task_code": "TEST-001",
            "task_title": "Test task",
            "owner_agent": "qa_agent",
            "status": "in_progress",
            "started_at": "2026-07-02T10:00:00",
            "updated_at": "2026-07-02T10:05:00",
            "stale_minutes": 20160.5,
        }]
        query, params = mock_cur.execute.call_args.args
        assert "COALESCE(updated_at, started_at, assigned_at, created_at)" in query
        assert params == (60, 20)

    def test_stale_task_threshold_must_be_positive(self):
        mock_conn, mock_cur = _mock_conn()

        try:
            list_stale_tasks(mock_conn, threshold_minutes=0)
        except ValueError as exc:
            assert "threshold_minutes" in str(exc)
        else:
            raise AssertionError("expected ValueError")
        mock_cur.execute.assert_not_called()


class TestRetryJobRun:
    def test_retries_failed_job(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[7])
        assert retry_job_run(mock_conn, 7, max_retries=2) is True
        assert "status = 'running'" in mock_cur.execute.call_args[0][0]
        mock_conn.commit.assert_called_once()

    def test_rejects_negative_budget(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[7])
        try:
            retry_job_run(mock_conn, 7, max_retries=-1)
        except ValueError as exc:
            assert "max_retries" in str(exc)
        else:
            raise AssertionError("expected ValueError")
        mock_cur.execute.assert_not_called()


class TestTaskArtifacts:
    def test_adds_artifact_with_metadata(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[9])
        result = add_task_artifact(mock_conn, {
            "task_id": 5, "artifact_type": "test_report",
            "artifact_path": "reports/test.txt", "metadata": {"passed": 3},
        })
        assert result == 9
        assert '"passed": 3' in mock_cur.execute.call_args[0][1]["metadata"]

    def test_lists_artifacts(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[(9, 5, "test_report", "x", "ok", "abc", {}, now)])
        result = list_task_artifacts(mock_conn, 5)
        assert result[0]["artifact_hash"] == "abc"


class TestListAgentTasks:
    def test_returns_formatted_task_list(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, "T-001", "Title", "general", "agent_x", "high", "L2", "created",
             "scope", True, "codex", now, now, now, now, now),
        ])

        result = list_agent_tasks(mock_conn)
        assert len(result) == 1
        assert result[0]["task_code"] == "T-001"
        assert result[0]["status"] == "created"

    def test_filters_by_status_and_agent(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_agent_tasks(mock_conn, status="completed", owner_agent="agent_x")
        assert result == []
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["status"] == "completed"
        assert call_args["owner_agent"] == "agent_x"


class TestGetAgentTask:
    def test_returns_full_task_details(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchone=[
            1, "T-001", "Title", "general", "agent_x", "high", "L2", "created",
            "scope", '{"key":"val"}', '["crit1","crit2"]', True, "codex",
            now, now, now, now,
        ])

        result = get_agent_task(mock_conn, "T-001")
        assert result is not None
        assert result["task_code"] == "T-001"
        assert result["human_review_required"] is True

    def test_returns_none_for_unknown_task(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = get_agent_task(mock_conn, "UNKNOWN")
        assert result is None


class TestWriteAuditLog:
    def test_inserts_and_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        entry = {"agent_name": "test_agent", "action_type": "execute"}
        result = write_audit_log(mock_conn, entry)
        assert result == 1
        mock_conn.commit.assert_called_once()

    def test_json_serializes_lists(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        entry = {
            "agent_name": "test",
            "action_type": "deploy",
            "files_changed": ["a.py", "b.py"],
            "tables_touched": ["teams"],
        }
        write_audit_log(mock_conn, entry)
        call_args = mock_cur.execute.call_args[0][1]
        assert "a.py" in call_args["files_changed"]

    def test_handles_none_optional_fields(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        entry = {"agent_name": "test", "action_type": "read"}
        write_audit_log(mock_conn, entry)
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["files_changed"] is None
        assert call_args["tables_touched"] is None


class TestListAuditLogs:
    def test_returns_formatted_list(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, 5, "agent_x", "deploy", "cmd", "success", "All good", now),
        ])

        result = list_audit_logs(mock_conn)
        assert len(result) == 1
        assert result[0]["agent_name"] == "agent_x"
        assert result[0]["result_status"] == "success"

    def test_filters_by_task_id(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_audit_logs(mock_conn, task_id=5)
        assert result == []
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["task_id"] == 5


class TestJobRuns:
    def test_recovers_interrupted_runs_for_owned_job_codes(self):
        mock_conn, mock_cur = _mock_conn(rowcount=2)

        recovered = recover_interrupted_job_runs(
            mock_conn,
            ["official_odds_snapshot"],
            reason="worker restarted",
        )

        assert recovered == 2
        query, params = mock_cur.execute.call_args.args
        assert "status = 'failed'" in query
        assert "job_code = ANY" in query
        assert params == ("worker restarted", ["official_odds_snapshot"])
        mock_conn.commit.assert_called_once()

    def test_recovery_skips_database_work_without_owned_jobs(self):
        mock_conn, mock_cur = _mock_conn()

        assert recover_interrupted_job_runs(mock_conn, []) == 0

        mock_cur.execute.assert_not_called()
        mock_conn.commit.assert_not_called()

    def test_start_job_run_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[100])

        job = {"job_code": "JOB-001", "job_name": "Test job", "owner_agent": "agent_x"}
        result = start_job_run(mock_conn, job)
        assert result == 100
        mock_conn.commit.assert_called_once()

    def test_finish_job_run_updates_and_returns_true(self):
        mock_conn, mock_cur = _mock_conn()

        result = finish_job_run(mock_conn, 100, "completed", output_refs={"count": 5})
        assert result is True
        mock_conn.commit.assert_called_once()

    def test_finish_job_run_with_error(self):
        mock_conn, mock_cur = _mock_conn()

        result = finish_job_run(mock_conn, 100, "failed", error="Something went wrong")
        assert result is True
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["error"] == "Something went wrong"

    def test_list_job_runs_with_filters(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, "J-001", "Job", "agent", "cron", "prod", "completed", 0,
             now, now, 5000, None, now),
        ])

        result = list_job_runs(mock_conn, status="completed")
        assert len(result) == 1
        assert result[0]["status"] == "completed"

    def test_start_job_run_returns_none_on_failure(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        job = {"job_code": "JOB-FAIL"}
        result = start_job_run(mock_conn, job)
        assert result is None


class TestReviewGatesAndReports:
    def test_create_review_gate_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        gate = {"task_id": 5, "gate_type": "auto", "reason": "High risk"}
        result = create_review_gate(mock_conn, gate)
        assert result == 1

    def test_resolve_review_gate_requires_valid_status(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])
        assert resolve_review_gate(mock_conn, 5, "human", "approved", "ok") is True
        assert mock_conn.commit.called

    def test_lists_review_gates(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, 5, "T-005", "Risk review", "human_review", "L4", None, "pending", None, None, now)
        ])
        result = list_review_gates(mock_conn, review_status="pending")
        assert result[0]["task_code"] == "T-005"
        assert result[0]["review_status"] == "pending"

    def test_resolve_review_gate_rejects_unknown_status(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])
        try:
            resolve_review_gate(mock_conn, 5, "human", "pending")
        except ValueError as exc:
            assert "approved or rejected" in str(exc)
        else:
            raise AssertionError("expected ValueError")
        mock_cur.execute.assert_not_called()

    def test_create_review_report_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        report = {
            "task_id": 5,
            "report_type": "qa",
            "test_command": "pytest",
            "pass_count": 10,
            "fail_count": 0,
        }
        result = create_review_report(mock_conn, report)
        assert result == 1

    def test_create_review_report_json_serializes_report(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        report = {"task_id": 5, "report_json": {"summary": "All tests passed"}}
        create_review_report(mock_conn, report)
        call_args = mock_cur.execute.call_args[0][1]
        assert "summary" in call_args["report_json"]
