-- FQP: CONCURRENT_INDEX idx_ai_job_runs_prediction_recovery
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ai_job_runs_prediction_recovery
    ON public.ai_job_runs ((input_snapshot_refs->>'execution_protocol'), id)
    WHERE job_code='model_prediction' AND status='running';
