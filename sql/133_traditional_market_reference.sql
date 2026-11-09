SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_fixture_market_references (
    fixture_id BIGINT NOT NULL REFERENCES football_fixtures(id),
    kickoff_at TIMESTAMPTZ NOT NULL,
    target_at TIMESTAMPTZ NOT NULL CHECK (target_at < kickoff_at),
    schedule_basis JSONB NOT NULL CHECK (jsonb_typeof(schedule_basis) = 'object'),
    checks INTEGER NOT NULL DEFAULT 1 CHECK (checks BETWEEN 1 AND 4),
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_error TEXT CHECK (last_error IN ('fixture_unverified','quote_unavailable','source_unavailable')),
    quote_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    reference JSONB,
    PRIMARY KEY (fixture_id, kickoff_at, target_at),
    CHECK (
        (reference IS NULL AND quote_at IS NULL AND observed_at IS NULL AND published_at IS NULL)
        OR (
            reference IS NOT NULL AND quote_at IS NOT NULL AND observed_at IS NOT NULL
            AND published_at IS NOT NULL AND last_error IS NULL
            AND reference @> '{"method":"market_1x2_proportional/v1","source":"titan007"}'
            AND reference ?& ARRAY['source_match_id','company_id','company_name','odds',
                                    'probabilities','source_url','response_sha256','fixture_pages']
            AND reference->'odds' ?& ARRAY['h','d','a']
            AND reference->'probabilities' ?& ARRAY['h','d','a']
            AND observed_at >= target_at AND quote_at <= observed_at
            AND quote_at >= observed_at - INTERVAL '45 minutes'
            AND observed_at <= published_at AND published_at < kickoff_at
        )
    )
);

CREATE TRIGGER protect_published_fixture_market_reference
    BEFORE UPDATE OR DELETE ON football_fixture_market_references
    FOR EACH ROW WHEN (OLD.published_at IS NOT NULL)
    EXECUTE FUNCTION protect_football_fixture_identity();

DO $$ BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'fqp') THEN
        GRANT SELECT, INSERT ON football_fixture_market_references TO fqp;
        GRANT UPDATE (checks,last_checked_at,last_error,schedule_basis,quote_at,observed_at,
                      published_at,reference) ON football_fixture_market_references TO fqp;
    END IF;
END $$;
