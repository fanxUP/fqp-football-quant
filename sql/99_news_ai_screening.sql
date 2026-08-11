-- News Intelligence P5: auditable AI screening without writing model text into business facts.
CREATE TABLE IF NOT EXISTS news_article_screenings (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL REFERENCES news_articles_raw(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    screening_method VARCHAR(24) NOT NULL
        CHECK (screening_method IN ('rule', 'llm', 'rule_fallback')),
    accepted BOOLEAN NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    relevance_score NUMERIC(8,6) NOT NULL DEFAULT 0
        CHECK (relevance_score >= 0 AND relevance_score <= 1),
    requires_review BOOLEAN NOT NULL DEFAULT TRUE,
    normalized_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (article_id, match_id)
);

CREATE INDEX IF NOT EXISTS idx_news_article_screenings_match
    ON news_article_screenings (match_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_article_screenings_review
    ON news_article_screenings (requires_review, accepted, created_at DESC);

CREATE TABLE IF NOT EXISTS news_model_invocations (
    id BIGSERIAL PRIMARY KEY,
    screening_id BIGINT NOT NULL REFERENCES news_article_screenings(id) ON DELETE CASCADE,
    article_id BIGINT NOT NULL REFERENCES news_articles_raw(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    agent_code VARCHAR(64) NOT NULL DEFAULT 'news_extraction_agent',
    provider_code VARCHAR(64),
    model VARCHAR(160),
    status VARCHAR(16) NOT NULL CHECK (status IN ('succeeded', 'failed')),
    prompt_sha256 CHAR(64) NOT NULL,
    response_sha256 CHAR(64),
    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_model_invocations_created
    ON news_model_invocations (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_model_invocations_article_match
    ON news_model_invocations (article_id, match_id, created_at DESC);
