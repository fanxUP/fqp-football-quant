-- Keep global prediction and dashboard recommendation reads responsive as
-- model history grows. Both paths only expose validated pre-kickoff evidence.
CREATE INDEX IF NOT EXISTS idx_predictions_valid_recent
    ON model_predictions (predict_time DESC, ev DESC, id DESC)
    WHERE validation_status = 'valid';

CREATE INDEX IF NOT EXISTS idx_predictions_valid_positive_ev
    ON model_predictions (ev DESC, id DESC)
    WHERE validation_status = 'valid'
      AND ev IS NOT NULL;

CREATE OR REPLACE VIEW v_dashboard_recommendation_summary AS
SELECT
    mp.id AS prediction_id,
    m.business_date,
    m.id AS match_id,
    m.official_match_code,
    m.league_name,
    m.home_team_name,
    m.away_team_name,
    m.kickoff_time,
    mp.play_type,
    mp.option_code,
    mp.model_probability,
    mp.market_probability,
    mp.model_probability - mp.market_probability AS probability_edge,
    mp.ev,
    mp.fair_odds,
    mp.confidence_score,
    mp.risk_score,
    mv.model_name,
    mv.version AS model_version
FROM model_predictions mp
JOIN official_matches m ON m.id = mp.match_id
JOIN model_versions mv ON mv.id = mp.model_version_id
WHERE mp.validation_status = 'valid'
  AND mp.ev IS NOT NULL
  AND mp.predict_time < m.kickoff_time;
