import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.agents.task_queue import check_job_dependencies, start_tracked_job


def test_empty_dependencies_are_allowed():
    check_job_dependencies([])


def test_latest_failed_dependency_blocks():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("official_schedule", "failed")]
    with patch("scripts.agents.task_queue.get_db") as get_db:
        get_db.return_value.__enter__.return_value = conn
        with pytest.raises(RuntimeError, match="official_schedule"):
            check_job_dependencies(["official_schedule"])


def test_latest_ok_dependency_is_completed_for_job_chaining():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("model_prediction", "ok")]
    with patch("scripts.agents.task_queue.get_db") as get_db:
        get_db.return_value.__enter__.return_value = conn
        check_job_dependencies(["model_prediction"])


def test_start_tracked_job_records_dependencies():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = [12]
    with patch("scripts.agents.task_queue.check_job_dependencies") as check, patch(
        "scripts.agents.task_queue.get_db"
    ) as get_db:
        get_db.return_value.__enter__.return_value = conn
        assert start_tracked_job("model_prediction", "model_agent", {}, ["official_odds_snapshot"]) == 12
        check.assert_called_once_with(["official_odds_snapshot"])
        params = cur.execute.call_args[0][1]
        assert json.loads(params["input_snapshot_refs"])["dependencies"] == ["official_odds_snapshot"]


def test_start_tracked_job_recovers_previous_interrupted_run():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = [13]
    cur.rowcount = 1

    with patch("scripts.agents.task_queue.get_db") as get_db:
        get_db.return_value.__enter__.return_value = conn
        assert start_tracked_job("official_odds_snapshot", "data_agent", {}) == 13

    recovery_query, recovery_params = cur.execute.call_args_list[0].args
    assert "status = 'failed'" in recovery_query
    assert recovery_params[1] == ["official_odds_snapshot"]
    assert cur.execute.call_count == 2
