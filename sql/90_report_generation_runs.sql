-- Immutable lifecycle metadata for automatically generated review reports.
-- This table is additive: it does not alter prediction, ticket, settlement, or risk facts.
CREATE TABLE IF NOT EXISTS report_generation_runs (
    id BIGSERIAL PRIMARY KEY,
    report_type VARCHAR(16) NOT NULL CHECK (report_type IN ('daily', 'weekly', 'monthly')),
    period_key VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('waiting', 'ready', 'completed', 'skipped', 'failed')),
    readiness_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_snapshot_hash VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP,
    UNIQUE (report_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_report_generation_runs_status_updated
    ON report_generation_runs (status, updated_at DESC);
