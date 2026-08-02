-- Human-initiated agent workspace records. Model output is retained only as untrusted text.

CREATE TABLE IF NOT EXISTS agent_workspace_tasks (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    agent_code VARCHAR(64) NOT NULL,
    provider_code VARCHAR(64) NOT NULL,
    model VARCHAR(160) NOT NULL,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_length(prompt) BETWEEN 1 AND 8000),
    CHECK (char_length(response) BETWEEN 1 AND 12000)
);

CREATE INDEX IF NOT EXISTS idx_agent_workspace_tasks_created
    ON agent_workspace_tasks (created_at DESC, id DESC);
