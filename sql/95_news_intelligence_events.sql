-- News Intelligence P2: structured events and independently reviewable evidence.
CREATE TABLE IF NOT EXISTS news_events (
    id BIGSERIAL PRIMARY KEY,
    event_fingerprint VARCHAR(128) NOT NULL UNIQUE,
    event_type VARCHAR(32) NOT NULL CHECK (event_type IN (
        'injury', 'suspension', 'return', 'expected_lineup', 'official_lineup',
        'rotation', 'manager_change', 'schedule_pressure', 'internal_issue',
        'morale_positive', 'morale_negative'
    )),
    direction VARCHAR(16) NOT NULL CHECK (direction IN ('positive', 'negative', 'neutral')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    severity_score NUMERIC(8,6) NOT NULL DEFAULT 0 CHECK (severity_score >= 0 AND severity_score <= 1),
    confidence_score NUMERIC(8,6) NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    match_relevance_score NUMERIC(8,6) NOT NULL DEFAULT 1
        CHECK (match_relevance_score >= 0 AND match_relevance_score <= 1),
    verification_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'verified', 'rejected', 'conflicting')),
    occurred_at TIMESTAMPTZ,
    first_available_at TIMESTAMPTZ NOT NULL,
    extraction_method VARCHAR(24) NOT NULL CHECK (extraction_method IN ('rule', 'provider', 'llm')),
    extraction_version VARCHAR(64) NOT NULL,
    extraction_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_events_available
    ON news_events (first_available_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_events_status_type
    ON news_events (verification_status, event_type, first_available_at DESC);

CREATE TABLE IF NOT EXISTS news_event_entities (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    match_id BIGINT REFERENCES official_matches(id),
    team_id BIGINT REFERENCES teams(id),
    player_id BIGINT REFERENCES players(id),
    entity_role VARCHAR(24) NOT NULL
        CHECK (entity_role IN ('home', 'away', 'subject', 'related')),
    entity_name TEXT,
    link_confidence NUMERIC(8,6) NOT NULL DEFAULT 1
        CHECK (link_confidence >= 0 AND link_confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (match_id IS NOT NULL OR team_id IS NOT NULL OR player_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_event_entities_unique
    ON news_event_entities (
        event_id,
        COALESCE(match_id, 0),
        COALESCE(team_id, 0),
        COALESCE(player_id, 0),
        entity_role
    );
CREATE INDEX IF NOT EXISTS idx_news_event_entities_match
    ON news_event_entities (match_id, event_id DESC)
    WHERE match_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS news_event_evidence (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    article_id BIGINT NOT NULL REFERENCES news_articles_raw(id),
    evidence_role VARCHAR(20) NOT NULL DEFAULT 'primary'
        CHECK (evidence_role IN ('primary', 'corroborating', 'contradicting')),
    verification_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'verified', 'rejected')),
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_news_event_evidence_event
    ON news_event_evidence (event_id, available_at, id);

CREATE TABLE IF NOT EXISTS news_event_reviews (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('verified', 'rejected', 'pending')),
    review_note TEXT,
    reviewer VARCHAR(64) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_event_reviews_event
    ON news_event_reviews (event_id, created_at DESC, id DESC);
