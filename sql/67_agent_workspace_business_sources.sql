-- Optional provenance for manually triggered business interpretation tasks.
-- Existing generic workspace tasks remain valid and retain NULL source metadata.

ALTER TABLE agent_workspace_tasks
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120);

CREATE INDEX IF NOT EXISTS idx_agent_workspace_tasks_source
    ON agent_workspace_tasks (source_type, source_ref, created_at DESC, id DESC)
    WHERE source_type IS NOT NULL;
