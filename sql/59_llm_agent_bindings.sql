-- Explicit, opt-in bindings between internal agents and enabled model providers.
-- A binding never changes scheduled jobs by itself; callers must opt in to the gateway.

CREATE TABLE IF NOT EXISTS llm_agent_bindings (
    agent_code VARCHAR(64) PRIMARY KEY,
    provider_code VARCHAR(64) NOT NULL REFERENCES llm_provider_configs(provider_code),
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_agent_bindings_enabled
    ON llm_agent_bindings (enabled) WHERE enabled;
