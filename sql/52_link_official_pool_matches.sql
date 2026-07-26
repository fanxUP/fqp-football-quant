-- Traditional pool rows and JC rows are separate official products, but an
-- exact same-date team pairing may safely share the canonical match identity.
UPDATE football_pool_issue_matches pool_match
SET match_id = (
    SELECT candidate.id
    FROM official_matches candidate
    WHERE candidate.home_team_name = pool_match.home_team_name
      AND candidate.away_team_name = pool_match.away_team_name
      AND candidate.kickoff_time::date = pool_match.kickoff_time::date
    ORDER BY candidate.id DESC
    LIMIT 1
)
WHERE pool_match.match_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_pool_issue_matches_match_id
    ON football_pool_issue_matches(match_id)
    WHERE match_id IS NOT NULL;
