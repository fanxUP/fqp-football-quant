-- News Intelligence P3: immutable point-in-time snapshots and isolated features.
ALTER TABLE news_events
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

UPDATE news_events
SET verified_at = updated_at
WHERE verification_status = 'verified' AND verified_at IS NULL;

CREATE TABLE IF NOT EXISTS match_news_snapshots (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    snapshot_label VARCHAR(16) NOT NULL
        CHECK (snapshot_label IN ('T24H', 'T6H', 'T90M', 'T45M', 'POST120')),
    snapshot_cutoff TIMESTAMPTZ NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
    checksum CHAR(64) NOT NULL,
    feature_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (match_id, snapshot_label, feature_version)
);

CREATE INDEX IF NOT EXISTS idx_match_news_snapshots_match_cutoff
    ON match_news_snapshots (match_id, snapshot_cutoff DESC, id DESC);

CREATE TABLE IF NOT EXISTS match_news_features (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL UNIQUE REFERENCES match_news_snapshots(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    snapshot_label VARCHAR(16) NOT NULL,
    home_positive_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    home_negative_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    away_positive_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    away_negative_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    home_net_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    away_net_impact NUMERIC(8,6) NOT NULL DEFAULT 0,
    verified_event_count INTEGER NOT NULL DEFAULT 0,
    pending_event_count INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    coverage_score NUMERIC(8,6) NOT NULL DEFAULT 0,
    confidence_score NUMERIC(8,6) NOT NULL DEFAULT 0,
    feature_vector JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_news_features_match_label
    ON match_news_features (match_id, snapshot_label, created_at DESC);
