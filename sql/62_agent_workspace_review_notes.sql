-- Optional human-review rationale. Kept separate from model output and bounded at rest.

ALTER TABLE agent_workspace_tasks
    ADD COLUMN IF NOT EXISTS review_note VARCHAR(2000);
