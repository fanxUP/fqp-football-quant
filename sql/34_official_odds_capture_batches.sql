-- Durable orchestration state for 30-minute and kickoff odds captures.
CREATE TABLE IF NOT EXISTS official_odds_capture_batches (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    scheduled_for TIMESTAMPTZ NOT NULL,
    capture_kind VARCHAR(16) NOT NULL
        CHECK (capture_kind IN ('opening', 'periodic', 'retry', 'final')),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'complete', 'partial', 'not_offered', 'failed')),
    expected_play_types TEXT[] NOT NULL DEFAULT '{}',
    captured_play_types TEXT[] NOT NULL DEFAULT '{}',
    snapshot_count INT NOT NULL DEFAULT 0,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (match_id, scheduled_for, capture_kind)
);

CREATE INDEX IF NOT EXISTS idx_odds_capture_batches_match_attempt
    ON official_odds_capture_batches(match_id, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_capture_batches_final
    ON official_odds_capture_batches(match_id, capture_kind)
    WHERE capture_kind = 'final';
