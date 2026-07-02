-- FQP Batch 6: Add missing analysis columns to market_efficiency_metrics
-- Required by feature_importance.py queries (model comparison, evaluation)

ALTER TABLE market_efficiency_metrics
    ADD COLUMN IF NOT EXISTS model_version_id BIGINT REFERENCES model_versions(id);

ALTER TABLE market_efficiency_metrics
    ADD COLUMN IF NOT EXISTS brier_score NUMERIC(10,6);

ALTER TABLE market_efficiency_metrics
    ADD COLUMN IF NOT EXISTS log_loss NUMERIC(10,6);

ALTER TABLE market_efficiency_metrics
    ADD COLUMN IF NOT EXISTS rps NUMERIC(10,6);

CREATE INDEX IF NOT EXISTS idx_mem_model_version
    ON market_efficiency_metrics(model_version_id);
