-- Cold-result risk features for pre-match model snapshots.
-- Values are built from settled historical matches strictly before kickoff.

ALTER TABLE match_feature_snapshots
    ADD COLUMN IF NOT EXISTS upset_risk_score NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS league_upset_rate NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS home_team_upset_rate NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS away_team_upset_rate NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS upset_risk_confidence NUMERIC(10,6);
