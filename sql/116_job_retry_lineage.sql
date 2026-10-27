-- Each retry has its own execution ID. Never reopen or rewrite a failed parent;
-- old finishers must not be able to terminate a subsequent execution.
-- Nullable for all existing history: no inferred links or retry-count backfill.
-- Preflight table/index size and ALTER/CREATE lock time on a production copy.
ALTER TABLE ai_job_runs
    ADD COLUMN retry_of_run_id BIGINT REFERENCES ai_job_runs(id),
    ADD CONSTRAINT chk_ai_job_runs_retry_not_self
        CHECK (retry_of_run_id IS NULL OR retry_of_run_id <> id);

-- The partial index avoids indexing unlinked history. ON CONFLICT uses this
-- constraint to serialize concurrent attempts without altering the parent row.
CREATE UNIQUE INDEX idx_ai_job_runs_retry_parent
    ON ai_job_runs(retry_of_run_id) WHERE retry_of_run_id IS NOT NULL;
