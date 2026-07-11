from scripts.jobs.run_scheduler import _audited_job


def test_self_tracked_job_is_not_wrapped_again():
    def job():
        return "tracked"

    wrapped = _audited_job("run_model_prediction", "模型预测", "model_agent", job)
    assert wrapped is job


def test_legacy_job_still_gets_scheduler_wrapper():
    def job():
        return "legacy"

    wrapped = _audited_job("legacy_job", "旧任务", "qa_agent", job)
    assert wrapped is not job


def test_scheduler_uses_completed_status_for_successful_legacy_jobs():
    # The wrapper's completion status is part of the shared ai_job_runs contract;
    # inspect the source to keep this test free of a real database side effect.
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'conn, run_id, "completed"' in source
    assert 'finish_job_run(conn, run_id, "success"' not in source
