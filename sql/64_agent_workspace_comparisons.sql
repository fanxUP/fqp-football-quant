-- Optional batch marker for one manually initiated, multi-model comparison.
-- A task remains independently reviewable and deletable.

ALTER TABLE agent_workspace_tasks
    ADD COLUMN IF NOT EXISTS comparison_id UUID;

CREATE INDEX IF NOT EXISTS idx_agent_workspace_tasks_comparison
    ON agent_workspace_tasks (comparison_id, created_at DESC, id DESC)
    WHERE comparison_id IS NOT NULL;
