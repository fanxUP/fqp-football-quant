-- One physical official-match database, trimmed to one selected season per event.
-- The selected window is refreshed from Sporttery's league archive; a small
-- number of missing boundaries are sourced from the competition organiser.
CREATE TABLE IF NOT EXISTS official_event_season_targets (
    league_name VARCHAR(128) PRIMARY KEY,
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
    CONSTRAINT official_event_season_targets_valid_window
        CHECK (season_start_date <= season_end_date)
);

CREATE INDEX IF NOT EXISTS idx_official_matches_league_business_date
    ON official_matches (league_name, business_date);

CREATE OR REPLACE FUNCTION enforce_official_event_season_target()
RETURNS trigger AS $$
BEGIN
    -- A fresh database is allowed to bootstrap before its first reconciliation.
    IF EXISTS (SELECT 1 FROM official_event_season_targets LIMIT 1)
       AND NOT EXISTS (
           SELECT 1
           FROM official_event_season_targets target
           WHERE target.league_name = NEW.league_name
             AND NEW.business_date BETWEEN target.season_start_date
                                       AND target.season_end_date
       ) THEN
        RAISE EXCEPTION 'official match %/% is outside selected event season',
            NEW.business_date, NEW.official_match_code
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_official_matches_event_season ON official_matches;
CREATE TRIGGER trg_official_matches_event_season
BEFORE INSERT OR UPDATE OF business_date, league_name ON official_matches
FOR EACH ROW EXECUTE FUNCTION enforce_official_event_season_target();
