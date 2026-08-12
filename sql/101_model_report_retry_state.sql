-- Bounded retry state for optional automatic model interpretations of completed reports.

ALTER TABLE report_generation_runs
    ADD COLUMN IF NOT EXISTS model_report_status VARCHAR(16),
    ADD COLUMN IF NOT EXISTS model_report_attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS model_report_last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS model_report_error_code VARCHAR(64);

ALTER TABLE report_generation_runs
    DROP CONSTRAINT IF EXISTS report_generation_runs_model_report_status_check;

ALTER TABLE report_generation_runs
    ADD CONSTRAINT report_generation_runs_model_report_status_check
    CHECK (model_report_status IS NULL OR model_report_status IN ('completed', 'failed'));

ALTER TABLE report_generation_runs
    DROP CONSTRAINT IF EXISTS report_generation_runs_model_report_attempt_count_check;

ALTER TABLE report_generation_runs
    ADD CONSTRAINT report_generation_runs_model_report_attempt_count_check
    CHECK (model_report_attempt_count >= 0);
