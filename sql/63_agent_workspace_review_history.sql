-- Immutable history for human review transitions; task deletion cascades to its history.

CREATE TABLE IF NOT EXISTS agent_workspace_task_review_events (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES agent_workspace_tasks(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('confirmed', 'revoked')),
    review_note VARCHAR(2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_workspace_review_events_task_created
    ON agent_workspace_task_review_events (task_id, created_at DESC, id DESC);
