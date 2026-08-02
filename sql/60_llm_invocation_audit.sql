-- Metadata-only audit trail for explicit LLM calls. Prompts, replies and credentials are never persisted.

CREATE TABLE IF NOT EXISTS llm_invocation_audits (
    id BIGSERIAL PRIMARY KEY,
    agent_code VARCHAR(64) NOT NULL,
    provider_code VARCHAR(64),
    model VARCHAR(160),
    status VARCHAR(16) NOT NULL,
    prompt_length INTEGER NOT NULL DEFAULT 0,
    response_length INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('succeeded', 'failed')),
    CHECK (prompt_length >= 0),
    CHECK (response_length >= 0),
    CHECK (duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_audits_created
    ON llm_invocation_audits (created_at DESC);
