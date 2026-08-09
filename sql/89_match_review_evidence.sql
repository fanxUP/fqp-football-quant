-- Match-level review evidence: sourced, immutable context for human-reviewed reports.
CREATE TABLE IF NOT EXISTS match_review_evidence (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    evidence_phase VARCHAR(16) NOT NULL CHECK (evidence_phase IN ('pre_match', 'post_match')),
    source_name VARCHAR(128) NOT NULL,
    source_url TEXT NOT NULL,
    published_at TIMESTAMP,
    captured_at TIMESTAMP NOT NULL DEFAULT now(),
    headline TEXT NOT NULL,
    summary TEXT,
    reliability VARCHAR(16) NOT NULL DEFAULT 'unverified'
        CHECK (reliability IN ('official', 'verified', 'unverified')),
    raw_hash VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (match_id, evidence_phase, source_url, headline)
);

CREATE INDEX IF NOT EXISTS idx_match_review_evidence_match_phase
    ON match_review_evidence (match_id, evidence_phase, published_at ASC, id ASC);
