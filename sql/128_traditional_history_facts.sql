-- Keep traditional-pool schedule precision and product-scoped source results
-- on each issue slot. Do not rewrite official_matches or official_results.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE football_pool_issues
    ADD COLUMN source_game_no SMALLINT,
    ADD COLUMN source_game_no_source TEXT;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issues'::regclass
          AND conname='football_pool_source_game_no'
    ) THEN
        ALTER TABLE football_pool_issues
            ADD CONSTRAINT football_pool_source_game_no CHECK (
                source_game_no IS NULL
                OR (source_game_no_source IS NOT NULL AND (
                    source_game_no_source='sporttery_live_draw'
                    AND ((game_type='t14c' AND source_game_no=90)
                      OR (game_type='r9' AND source_game_no=91)
                      OR (game_type='bqc6' AND source_game_no=98)
                      OR (game_type='jq4' AND source_game_no=99))
                ))
                OR (source_game_no_source IS NOT NULL AND (
                    source_game_no_source='sporttery_history_api'
                    AND ((game_type IN ('t14c','r9') AND source_game_no=90)
                      OR (game_type='bqc6' AND source_game_no=98)
                      OR (game_type='jq4' AND source_game_no=94))
                ))
            );
    END IF;
END $$;

ALTER TABLE football_pool_issue_matches
    ADD COLUMN kickoff_date DATE,
    ADD COLUMN kickoff_time_precision TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN kickoff_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN source_full_home_goals SMALLINT,
    ADD COLUMN source_full_away_goals SMALLINT,
    ADD COLUMN source_half_home_goals SMALLINT,
    ADD COLUMN source_half_away_goals SMALLINT,
    ADD COLUMN source_product_result_code TEXT,
    ADD COLUMN source_result_semantics_key TEXT,
    ADD COLUMN source_result_source TEXT,
    ADD COLUMN source_result_evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issue_matches'::regclass
          AND conname='pool_kickoff_precision'
    ) THEN
        ALTER TABLE football_pool_issue_matches
            ADD CONSTRAINT pool_kickoff_precision CHECK (
                kickoff_time_precision IN ('unknown','date_only','minute','second')
                AND (
                    kickoff_time_precision NOT IN ('date_only','minute','second')
                    OR kickoff_date IS NOT NULL
                )
                AND (
                    kickoff_time_precision NOT IN ('minute','second')
                    OR (kickoff_time IS NOT NULL AND kickoff_time::date=kickoff_date)
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issue_matches'::regclass
          AND conname='pool_kickoff_evidence_object'
    ) THEN
        ALTER TABLE football_pool_issue_matches
            ADD CONSTRAINT pool_kickoff_evidence_object
            CHECK (jsonb_typeof(kickoff_evidence)='object');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issue_matches'::regclass
          AND conname='pool_traditional_scores_nonnegative'
    ) THEN
        ALTER TABLE football_pool_issue_matches
            ADD CONSTRAINT pool_traditional_scores_nonnegative CHECK (
                (source_full_home_goals IS NULL OR source_full_home_goals >= 0)
                AND (source_full_away_goals IS NULL OR source_full_away_goals >= 0)
                AND (source_half_home_goals IS NULL OR source_half_home_goals >= 0)
                AND (source_half_away_goals IS NULL OR source_half_away_goals >= 0)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issue_matches'::regclass
          AND conname='pool_traditional_result_evidence_object'
    ) THEN
        ALTER TABLE football_pool_issue_matches
            ADD CONSTRAINT pool_traditional_result_evidence_object
            CHECK (jsonb_typeof(source_result_evidence)='object');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='football_pool_issue_matches'::regclass
          AND conname='pool_traditional_result_semantics'
    ) THEN
        ALTER TABLE football_pool_issue_matches
            ADD CONSTRAINT pool_traditional_result_semantics CHECK (
                source_product_result_code IS NULL
                OR (source_result_semantics_key IS NOT NULL AND btrim(source_result_semantics_key)<>'')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_pool_issue_match_kickoff_date
    ON football_pool_issue_matches(kickoff_date,issue_id)
    WHERE kickoff_date IS NOT NULL;

-- Append-only fixture revision history (migration 125) will retain prior and
-- new values when a future audited correction updates these slot-level facts.
CREATE OR REPLACE VIEW football_pool_fixture_catalog AS
SELECT im.id AS membership_id, i.id AS issue_id, i.game_type, i.issue_no,
       i.source_game_type, im.match_order, im.fixture_id, im.match_id AS official_match_id,
       im.identity_status, im.identity_evidence, im.league_name,
       im.home_team_name, im.away_team_name, im.kickoff_time,
       im.source_match_id, im.source_raw_json,
       i.source_game_no,i.source_game_no_source,
       im.kickoff_date, im.kickoff_time_precision, im.kickoff_evidence,
       im.source_full_home_goals, im.source_full_away_goals,
       im.source_half_home_goals, im.source_half_away_goals,
       im.source_product_result_code, im.source_result_semantics_key,
       im.source_result_source, im.source_result_evidence
FROM football_pool_issue_matches im JOIN football_pool_issues i ON i.id = im.issue_id;

-- The restricted application role validates the exact applied migration before
-- a history import. The server runner always creates this ledger; CI's raw SQL
-- migration bootstrap may omit it, so grant only when the ledger is present.
DO $$ BEGIN
    IF to_regclass('local_schema_migrations') IS NOT NULL
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fqp') THEN
        EXECUTE 'GRANT SELECT ON TABLE local_schema_migrations TO fqp';
    END IF;
END $$;
