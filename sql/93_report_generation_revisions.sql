-- Preserve every replaced automatic report snapshot during auditable backfills.
CREATE TABLE IF NOT EXISTS report_generation_revisions (
    id BIGSERIAL PRIMARY KEY,
    report_type VARCHAR(16) NOT NULL CHECK (report_type IN ('daily', 'weekly', 'monthly')),
    period_key VARCHAR(32) NOT NULL,
    revision INT NOT NULL CHECK (revision > 0),
    previous_snapshot_json JSONB NOT NULL,
    previous_snapshot_hash VARCHAR(64),
    replacement_snapshot_hash VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (report_type, period_key, revision)
);

CREATE INDEX IF NOT EXISTS idx_report_generation_revisions_source
    ON report_generation_revisions (report_type, period_key, revision DESC);

GRANT SELECT, INSERT ON report_generation_revisions TO fqp;
GRANT USAGE, SELECT ON SEQUENCE report_generation_revisions_id_seq TO fqp;
