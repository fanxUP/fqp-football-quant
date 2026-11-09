SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

-- Sparse odds-only snapshots retain the match provenance without fake team FKs.
ALTER TABLE match_feature_snapshots
    ALTER COLUMN home_team_id DROP NOT NULL,
    ALTER COLUMN away_team_id DROP NOT NULL,
    ADD CONSTRAINT match_feature_snapshots_team_evidence
        CHECK ((home_team_id IS NOT NULL AND away_team_id IS NOT NULL)
            OR (home_team_id IS NULL AND away_team_id IS NULL
                AND feature_version='prematch_market_only/v1')) NOT VALID;

CREATE TABLE prematch_prediction_tasks (
    task_key TEXT PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id),
    play_type TEXT NOT NULL CHECK (play_type IN ('spf', 'rqspf')),
    kickoff_at TIMESTAMPTZ NOT NULL,
    target_at TIMESTAMPTZ NOT NULL CHECK (target_at < kickoff_at),
    schedule_basis JSONB NOT NULL CHECK (jsonb_typeof(schedule_basis) = 'object'),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_attempt_at TIMESTAMPTZ,
    quote_checked_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    run_id UUID REFERENCES model_prediction_runs(id),
    completed_at TIMESTAMPTZ,
    CHECK (completed_at IS NULL OR run_id IS NOT NULL)
);
CREATE INDEX idx_prematch_prediction_tasks_match ON prematch_prediction_tasks(match_id);
CREATE INDEX idx_prematch_prediction_tasks_quote_due ON prematch_prediction_tasks(target_at)
    WHERE completed_at IS NULL;

CREATE TABLE sporttery_schedule_notices (
    source_url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    raw_body TEXT,
    PRIMARY KEY (source_url, content_sha256)
);
CREATE INDEX idx_sporttery_schedule_notices_published ON sporttery_schedule_notices(published_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'fqp') THEN
        GRANT SELECT, INSERT, UPDATE ON prematch_prediction_tasks TO fqp;
        GRANT SELECT, INSERT ON sporttery_schedule_notices TO fqp;
    END IF;
END $$;
