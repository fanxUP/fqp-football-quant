-- Future scheduled/manual backtests have an explicit audit owner. A parameter
-- sweep owns several runs, so this is deliberately not a unique foreign key.
-- Do not infer links for historical rows from names or nearby timestamps.
-- Preflight production-copy DDL lock time and space before production apply.
ALTER TABLE backtest_runs
    ADD COLUMN ai_job_run_id BIGINT REFERENCES ai_job_runs(id);

CREATE INDEX idx_backtest_runs_ai_job_run
    ON backtest_runs(ai_job_run_id) WHERE ai_job_run_id IS NOT NULL;
