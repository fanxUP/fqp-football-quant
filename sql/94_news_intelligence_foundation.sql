-- News Intelligence P1: append-only discovery records linked only to official matches.
CREATE TABLE IF NOT EXISTS news_sources (
    id BIGSERIAL PRIMARY KEY,
    source_code VARCHAR(96) NOT NULL UNIQUE,
    source_name VARCHAR(160) NOT NULL,
    publisher_domain VARCHAR(255),
    source_level CHAR(1) NOT NULL CHECK (source_level IN ('S', 'A', 'B', 'C', 'D')),
    source_type VARCHAR(32) NOT NULL
        CHECK (source_type IN ('official', 'structured', 'media', 'social')),
    default_language VARCHAR(16),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_sources_domain
    ON news_sources (lower(publisher_domain))
    WHERE publisher_domain IS NOT NULL;

CREATE TABLE IF NOT EXISTS news_articles_raw (
    id BIGSERIAL PRIMARY KEY,
    provider_code VARCHAR(64) NOT NULL,
    external_id VARCHAR(255),
    source_id BIGINT NOT NULL REFERENCES news_sources(id),
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    content_excerpt TEXT,
    language VARCHAR(16),
    published_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL,
    content_hash VARCHAR(128) NOT NULL,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider_code, external_id),
    UNIQUE (canonical_url),
    CHECK (available_at >= published_at),
    CHECK (observed_at >= published_at)
);

CREATE INDEX IF NOT EXISTS idx_news_articles_available
    ON news_articles_raw (available_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_articles_source_published
    ON news_articles_raw (source_id, published_at DESC);

CREATE TABLE IF NOT EXISTS news_article_matches (
    article_id BIGINT NOT NULL REFERENCES news_articles_raw(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    relevance_score NUMERIC(8,6) NOT NULL DEFAULT 1.0
        CHECK (relevance_score >= 0 AND relevance_score <= 1),
    link_method VARCHAR(32) NOT NULL DEFAULT 'entity_match'
        CHECK (link_method IN ('provider', 'entity_match', 'manual')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (article_id, match_id)
);

CREATE INDEX IF NOT EXISTS idx_news_article_matches_match
    ON news_article_matches (match_id, article_id DESC);

CREATE TABLE IF NOT EXISTS news_ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    provider_code VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    requested_count INTEGER NOT NULL DEFAULT 0 CHECK (requested_count >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    error_message TEXT,
    cursor_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_ingestion_runs_provider_started
    ON news_ingestion_runs (provider_code, started_at DESC);
