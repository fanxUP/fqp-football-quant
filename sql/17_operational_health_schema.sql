-- 17_operational_health_schema.sql
-- Stage 8: Operational health monitoring, backup tracking, evidence chain audit,
-- and data contamination guard tables.

-- Daily operational health snapshot (Stage 8 KPIs)
CREATE TABLE IF NOT EXISTS operational_health_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    snapshot_time TIMESTAMP NOT NULL DEFAULT now(),

    -- Core Stage 8 metrics
    continuous_uptime_days INT,                     -- consecutive days without restart
    official_collection_success_rate NUMERIC(6,4),  -- target >= 0.98
    odds_snapshot_missing_rate NUMERIC(6,4),        -- target <= 0.02
    review_generation_success_rate NUMERIC(6,4),    -- target >= 0.99
    backup_success BOOLEAN,                         -- target = true (100%)
    evidence_chain_completeness_rate NUMERIC(6,4),  -- target = 1.00
    data_contamination_count INT DEFAULT 0,         -- target = 0

    -- Detailed counts for transparency
    total_official_matches INT,
    successful_official_collections INT,
    total_odds_snapshots_expected INT,
    missing_odds_snapshots INT,
    total_reviews_expected INT,
    successful_review_generations INT,
    total_recommendations INT,
    recommendations_with_full_chain INT,
    contamination_issues_found INT,

    -- System health
    scheduler_running BOOLEAN,
    worker_running BOOLEAN,
    api_responding BOOLEAN,
    db_responding BOOLEAN,
    disk_usage_pct NUMERIC(5,2),
    last_backup_at TIMESTAMP,

    -- Summary
    overall_health_status VARCHAR(32),  -- healthy / degraded / critical
    health_notes TEXT,
    raw_details JSONB,

    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(snapshot_date)
);

-- Backup execution log
CREATE TABLE IF NOT EXISTS backup_logs (
    id BIGSERIAL PRIMARY KEY,
    backup_type VARCHAR(32) NOT NULL,       -- full / incremental / manual
    backup_path TEXT,
    backup_size_bytes BIGINT,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    success BOOLEAN NOT NULL DEFAULT false,
    integrity_check_passed BOOLEAN,
    restore_test_passed BOOLEAN,
    error_message TEXT,
    backup_command TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Evidence chain audit log (per-recommendation traceability)
CREATE TABLE IF NOT EXISTS evidence_chain_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    audit_time TIMESTAMP NOT NULL DEFAULT now(),
    recommendation_id BIGINT,
    ticket_id BIGINT,

    -- Chain links (NULL = broken link)
    odds_snapshot_id BIGINT,        -- → official_odds_snapshots.id
    model_version_id BIGINT,        -- → model_versions.id
    feature_snapshot_id BIGINT,     -- → match_feature_snapshots.id
    prediction_id BIGINT,           -- → model_predictions.id

    -- Verification results
    chain_complete BOOLEAN NOT NULL DEFAULT false,
    broken_link_at VARCHAR(64),     -- which link is broken
    chain_details JSONB,

    -- Age checks (prevent stale data)
    odds_snapshot_age_seconds INT,         -- seconds before recommendation
    feature_snapshot_age_seconds INT,
    model_version_is_current BOOLEAN,

    created_at TIMESTAMP DEFAULT now()
);

-- Data contamination audit log (temporal integrity)
CREATE TABLE IF NOT EXISTS data_contamination_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    audit_time TIMESTAMP NOT NULL DEFAULT now(),

    -- What was checked
    check_type VARCHAR(64) NOT NULL,  -- pre_match_lineup / post_match_odds / result_leak / feature_leak
    match_id BIGINT,
    severity VARCHAR(16) NOT NULL DEFAULT 'info',  -- critical / warning / info

    -- Findings
    contamination_detected BOOLEAN NOT NULL DEFAULT false,
    detail TEXT,                     -- human-readable description
    evidence JSONB,                  -- timestamps, data sources, proof

    -- Resolution
    resolved BOOLEAN DEFAULT false,
    resolution_notes TEXT,

    created_at TIMESTAMP DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_health_snapshots_date ON operational_health_snapshots(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_backup_logs_started ON backup_logs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_chain_rec ON evidence_chain_audit_logs(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_chain_complete ON evidence_chain_audit_logs(chain_complete);
CREATE INDEX IF NOT EXISTS idx_contamination_match ON data_contamination_audit_logs(match_id);
CREATE INDEX IF NOT EXISTS idx_contamination_detected ON data_contamination_audit_logs(contamination_detected);
