"""Fixed-response backtest orchestration; no model/provider calls."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from scripts.backtest_engine import BacktestConfig
from scripts.jobs import run_backtest as job


def test_manual_bad_config_never_acquires_owner_or_starts_a_job():
    cfg = BacktestConfig()
    cfg.step_days = 0
    with patch.object(job, "backtest_execution") as owner:
        with pytest.raises(ValueError, match="step_days"):
            job.run_config(cfg)
    owner.assert_not_called()


@pytest.mark.parametrize(
    "grid",
    [
        {"step_days": [1, 0]},
        {"unknown": [1]},
        {"min_model_prob": [0.1] * 101},
        {"step_days": []},
    ],
)
def test_sweep_validates_every_candidate_before_any_execution(grid):
    with patch.object(job, "run_backtest_from_config") as execute:
        with pytest.raises(ValueError):
            job.run_parameter_sweep(MagicMock(), BacktestConfig(), grid)
    execute.assert_not_called()


def test_sweep_rejects_overlong_generated_names_before_first_execution():
    with patch.object(job, "run_backtest_from_config") as execute:
        with pytest.raises(ValueError, match="name"):
            job.run_parameter_sweep(
                MagicMock(), BacktestConfig(), {"description": ["短", "长" * 300]}
            )
    execute.assert_not_called()


def test_full_backtest_executes_before_connection_is_returned():
    conn = MagicMock()
    active = []

    @contextmanager
    def database():
        active.append(True)
        try:
            yield conn
        finally:
            active.pop()

    def execute(writer, **kwargs):
        assert active and writer is conn
        return {"status": "ok"}

    with (
        patch("apps.backend.src.db.get_db", database),
        patch.object(job, "run_full_backtest", execute),
    ):
        assert job._run_impl()["status"] == "ok"


def test_busy_owner_skips_without_starting_or_computing():
    @contextmanager
    def busy():
        yield None

    with (
        patch.object(job, "backtest_execution", busy, create=True),
        patch.object(job, "_run_impl") as execute,
        patch.object(job, "start_tracked_job", create=True) as start,
        patch.object(job, "finish_tracked_job", create=True) as finish,
    ):
        assert job.run() == {"status": "skipped", "reason": "backtest_execution_in_progress"}
    start.assert_not_called()
    finish.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize("mode", ["full", "model", "sweep"])
def test_every_mode_uses_owned_connection_and_persistent_job_id(mode):
    conn = MagicMock()
    function = {
        "full": "run_full_backtest",
        "model": "run_model_backtest",
        "sweep": "run_parameter_sweep",
    }[mode]
    with (
        patch("apps.backend.src.db.get_db") as database,
        patch.object(job, function, return_value={"status": "ok"}) as execute,
    ):
        job._run_impl(
            model_name="fixed" if mode == "model" else None,
            sweep=mode == "sweep",
            execution_conn=conn,
            ai_job_run_id=81,
        )
    database.assert_not_called()
    assert execute.call_args.args[0] is conn
    assert execute.call_args.kwargs["ai_job_run_id"] == 81


def test_parameter_sweep_does_not_hide_failed_storage_or_continue():
    with patch.object(
        job,
        "run_backtest_from_config",
        return_value={"status": "store_failed", "run_id": 42, "store_error": "write failed"},
    ) as execute:
        result = job.run_parameter_sweep(
            MagicMock(), BacktestConfig(), {"min_model_prob": [0.2, 0.3]}, ai_job_run_id=81
        )
    assert result["status"] == "store_failed" and result["run_id"] == 42
    assert execute.call_count == 1 and execute.call_args.kwargs["ai_job_run_id"] == 81


def test_cleanup_failure_is_logged_and_original_exception_is_preserved(caplog):
    conn = MagicMock()
    with (
        patch.object(job, "_run_impl", side_effect=ValueError("computation failure")),
        patch.object(job, "reconcile_backtest_job", side_effect=RuntimeError("database lost")),
        pytest.raises(ValueError, match="computation failure"),
    ):
        job._execute_owned(conn, 81, None, None, False, False)
    conn.rollback.assert_called_once()
    assert "leaving durable facts" in caplog.text
