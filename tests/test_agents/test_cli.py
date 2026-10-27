"""The manual audit CLI must hand off the distinct retry execution identity."""

import ast
from unittest.mock import MagicMock, patch

import pytest

from scripts.agents import cli


@pytest.mark.parametrize("new_id", [91, None])
def test_retry_output_distinguishes_original_and_new_execution(capsys, new_id):
    with (
        patch.object(cli, "get_db") as get_db,
        patch.object(cli, "retry_job_run", return_value=new_id) as retry,
    ):
        conn = MagicMock()
        get_db.return_value.__enter__.return_value = conn
        assert cli.main(["job-retry", "90", "--max-retries", "1"]) == 0
        retry.assert_called_once_with(conn, 90, max_retries=1)
    result = ast.literal_eval(capsys.readouterr().out.strip())
    assert result == {"run_id": 90, "retried": new_id is not None, "retry_run_id": new_id}


def test_finish_uses_the_retry_identity_supplied_by_the_operator(capsys):
    with (
        patch.object(cli, "get_db") as get_db,
        patch.object(cli, "finish_job_run", return_value=True) as finish,
    ):
        conn = get_db.return_value.__enter__.return_value
        assert cli.main(["job-finish", "91", "completed"]) == 0
        finish.assert_called_once_with(conn, 91, "completed", error=None)
    assert ast.literal_eval(capsys.readouterr().out.strip())["run_id"] == 91
