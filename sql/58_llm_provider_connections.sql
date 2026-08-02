-- Encrypted model-provider credentials. Plain API keys must never enter logs or API responses.

CREATE TABLE IF NOT EXISTS llm_provider_configs (
    provider_code VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(80) NOT NULL,
    base_url TEXT NOT NULL,
    default_model VARCHAR(160) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    api_key_encrypted TEXT,
    last_test_at TIMESTAMPTZ,
    last_test_status VARCHAR(16),
    last_test_message VARCHAR(500),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (last_test_status IS NULL OR last_test_status IN ('passed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_llm_provider_configs_enabled
    ON llm_provider_configs (enabled) WHERE enabled;
