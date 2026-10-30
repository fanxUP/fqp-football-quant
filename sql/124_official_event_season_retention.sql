-- Separate durable historical admission from the current-season selector.
-- Existing match/result/ticket IDs and previously applied migration32 stay intact.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS official_event_season_retention (
    league_name VARCHAR(128) NOT NULL,
    season_name VARCHAR(64) NOT NULL,
    season_start_date DATE NOT NULL,
    season_end_date DATE NOT NULL,
    selection_reason VARCHAR(32) NOT NULL,
    boundary_source VARCHAR(32) NOT NULL,
    official_league_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_url TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (league_name, season_name, season_start_date, season_end_date),
    CONSTRAINT official_event_season_retention_valid_window
        CHECK (season_start_date <= season_end_date)
);

-- Retain distinct source windows, including earlier/wider versions. A later
-- shorter season observation cannot revoke previously admitted history.
INSERT INTO official_event_season_retention (
    league_name, season_name, season_start_date, season_end_date,
    selection_reason, boundary_source, official_league_refs,
    source_url, as_of_date, raw_json, created_at, updated_at
)
SELECT league_name, season_name, season_start_date, season_end_date,
       selection_reason, boundary_source, official_league_refs,
       source_url, as_of_date, raw_json, created_at, updated_at
FROM official_event_season_targets
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION enforce_official_event_season_target()
RETURNS trigger AS $$
BEGIN
    -- Preserve fresh-database bootstrap semantics; never collapse disjoint
    -- windows to a continuous min/max range. Dates are JC business dates,
    -- not proof of a fixture's canonical competition-season membership.
    IF EXISTS (SELECT 1 FROM official_event_season_retention LIMIT 1)
       AND NOT EXISTS (
           SELECT 1
           FROM official_event_season_retention target
           WHERE target.league_name = NEW.league_name
             AND NEW.business_date BETWEEN target.season_start_date
                                       AND target.season_end_date
       ) THEN
        RAISE EXCEPTION 'official match %/% is outside retained event seasons',
            NEW.business_date, NEW.official_match_code
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
