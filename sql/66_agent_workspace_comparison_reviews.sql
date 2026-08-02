-- A human conclusion is separate from every untrusted model response.

ALTER TABLE agent_workspace_comparisons
    ADD COLUMN IF NOT EXISTS review_note TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
