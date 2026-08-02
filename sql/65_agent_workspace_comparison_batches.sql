-- Durable, manual-only comparison batch metadata. Task content remains in agent_workspace_tasks.

CREATE TABLE IF NOT EXISTS agent_workspace_comparisons (
    id UUID PRIMARY KEY,
    requested_agent_codes TEXT[] NOT NULL,
    requested_count SMALLINT NOT NULL CHECK (requested_count BETWEEN 2 AND 3),
    succeeded_count SMALLINT NOT NULL DEFAULT 0 CHECK (succeeded_count >= 0),
    failed_count SMALLINT NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_workspace_comparisons_created
    ON agent_workspace_comparisons (created_at DESC, id DESC);
