-- Durable startup recovery ledger.
-- This migration records the recovery decision before any future execution.
CREATE TABLE IF NOT EXISTS startup_recovery_sessions (
    id BIGSERIAL PRIMARY KEY,
    boot_id VARCHAR(128) NOT NULL,
    outage_start TIMESTAMPTZ,
    outage_end TIMESTAMPTZ NOT NULL,
    mode VARCHAR(16) NOT NULL CHECK (mode IN ('dry_run', 'plan', 'execute')),
    status VARCHAR(16) NOT NULL CHECK (status IN ('planned', 'running', 'completed', 'failed', 'blocked')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (boot_id)
);

CREATE TABLE IF NOT EXISTS startup_recovery_task_runs (
    id BIGSERIAL PRIMARY KEY,
    recovery_session_id BIGINT NOT NULL REFERENCES startup_recovery_sessions(id) ON DELETE CASCADE,
    task_code VARCHAR(128) NOT NULL,
    business_window_start TIMESTAMPTZ,
    business_window_end TIMESTAMPTZ,
    idempotency_key VARCHAR(255) NOT NULL,
    strategy VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('planned', 'skipped', 'running', 'completed', 'failed', 'blocked')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    output_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_startup_recovery_sessions_status
    ON startup_recovery_sessions (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_startup_recovery_task_runs_pending
    ON startup_recovery_task_runs (status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_startup_recovery_task_runs_session
    ON startup_recovery_task_runs (recovery_session_id, id);
