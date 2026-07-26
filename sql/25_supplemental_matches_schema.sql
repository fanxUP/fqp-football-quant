-- Third-party season schedules/results. Never use this table as the official
-- lottery schedule; Sporttery remains the only source for official_matches.
CREATE TABLE IF NOT EXISTS supplemental_matches (
    id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(64) NOT NULL,
    source_match_id VARCHAR(128) NOT NULL,
    competition_season_id BIGINT REFERENCES competition_seasons(id),
    home_team_id BIGINT REFERENCES teams(id),
    away_team_id BIGINT REFERENCES teams(id),
    league_name VARCHAR(128) NOT NULL,
    home_team_name VARCHAR(128) NOT NULL,
    away_team_name VARCHAR(128) NOT NULL,
    kickoff_time TIMESTAMP NOT NULL,
    round_name VARCHAR(64),
    match_status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    full_home_goals INT,
    full_away_goals INT,
    half_home_goals INT,
    half_away_goals INT,
    source_url TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE (source_name, source_match_id)
);

CREATE INDEX IF NOT EXISTS idx_supplemental_matches_league_time
    ON supplemental_matches (league_name, kickoff_time);

ALTER TABLE supplemental_matches
    ADD COLUMN IF NOT EXISTS competition_season_id BIGINT REFERENCES competition_seasons(id);
ALTER TABLE supplemental_matches
    ADD COLUMN IF NOT EXISTS home_team_id BIGINT REFERENCES teams(id);
ALTER TABLE supplemental_matches
    ADD COLUMN IF NOT EXISTS away_team_id BIGINT REFERENCES teams(id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'supplemental_matches_nonnegative_score'
    ) THEN
        ALTER TABLE supplemental_matches
            ADD CONSTRAINT supplemental_matches_nonnegative_score
            CHECK (
                (full_home_goals IS NULL OR full_home_goals >= 0)
                AND (full_away_goals IS NULL OR full_away_goals >= 0)
                AND (half_home_goals IS NULL OR half_home_goals >= 0)
                AND (half_away_goals IS NULL OR half_away_goals >= 0)
            ) NOT VALID;
    END IF;
END $$;

UPDATE supplemental_matches sm
SET competition_season_id = cs.id
FROM competition_seasons cs
JOIN competitions c ON c.id = cs.competition_id
JOIN seasons s ON s.id = cs.season_id
WHERE sm.competition_season_id IS NULL
  AND c.competition_name_cn = sm.league_name
  AND s.season_code = '2026';

UPDATE supplemental_matches sm
SET home_team_id = ta.team_id
FROM team_aliases ta
WHERE sm.home_team_id IS NULL
  AND ta.source_name = '500.com'
  AND ta.alias_name = sm.home_team_name;

UPDATE supplemental_matches sm
SET away_team_id = ta.team_id
FROM team_aliases ta
WHERE sm.away_team_id IS NULL
  AND ta.source_name = '500.com'
  AND ta.alias_name = sm.away_team_name;

CREATE INDEX IF NOT EXISTS idx_supplemental_matches_competition_season
    ON supplemental_matches (competition_season_id, kickoff_time);
CREATE INDEX IF NOT EXISTS idx_supplemental_matches_home_team
    ON supplemental_matches (home_team_id, kickoff_time);
CREATE INDEX IF NOT EXISTS idx_supplemental_matches_away_team
    ON supplemental_matches (away_team_id, kickoff_time);
