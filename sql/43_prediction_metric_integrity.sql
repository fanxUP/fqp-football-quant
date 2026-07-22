-- Make model metrics auditable against one exact official odds option.
ALTER TABLE model_predictions
    ADD COLUMN IF NOT EXISTS break_even_probability NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS market_edge NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS breakeven_edge NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(16) NOT NULL DEFAULT 'valid',
    ADD COLUMN IF NOT EXISTS validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(32) NOT NULL DEFAULT 'legacy';

CREATE INDEX IF NOT EXISTS idx_odds_match_play_option_time
    ON official_odds_snapshots (
        match_id, play_type, option_code, snapshot_time DESC, id DESC
    );

CREATE INDEX IF NOT EXISTS idx_predictions_validation_latest
    ON model_predictions (
        validation_status, match_id, model_version_id,
        play_type, option_code, predict_time DESC, id DESC
    );

-- Historical SPF/RQSPF rows sometimes pointed every outcome at one snapshot.
-- Resolve the latest exact option that was available when the prediction ran.
WITH exact_snapshots AS MATERIALIZED (
    SELECT
        mp.id AS prediction_id,
        odds.id AS odds_snapshot_id,
        odds.sp_value
    FROM model_predictions mp
    JOIN LATERAL (
        SELECT candidate.id, candidate.sp_value
        FROM official_odds_snapshots candidate
        WHERE candidate.match_id = mp.match_id
          AND candidate.play_type = mp.play_type
          AND candidate.option_code = CASE mp.option_code
              WHEN '3' THEN 'h'
              WHEN '1' THEN 'd'
              WHEN '0' THEN 'a'
              ELSE mp.option_code
          END
          AND candidate.snapshot_time <= mp.predict_time
        ORDER BY candidate.snapshot_time DESC, candidate.id DESC
        LIMIT 1
    ) odds ON true
)
UPDATE model_predictions mp
SET odds_snapshot_id = exact.odds_snapshot_id,
    break_even_probability = 1.0 / exact.sp_value,
    market_edge = mp.model_probability - mp.market_probability,
    breakeven_edge = mp.model_probability - (1.0 / exact.sp_value),
    ev = mp.model_probability * exact.sp_value - 1.0,
    calculation_version = 'market_metrics_v2_repaired'
FROM exact_snapshots exact
WHERE exact.prediction_id = mp.id
  AND exact.sp_value > 1;

-- Predictions from the old implementation were market-seeded rather than
-- independently trained. Keep them for benchmark history, but never allow
-- them to masquerade as independent recommendation evidence.
UPDATE model_predictions
SET uncertainty_reason = COALESCE(uncertainty_reason, '{}'::jsonb)
        || jsonb_build_object('model_independent', false)
WHERE NOT (COALESCE(uncertainty_reason, '{}'::jsonb) ? 'model_independent');

UPDATE model_predictions
SET validation_status = 'invalid',
    validation_errors = validation_errors || '["MISSING_EXACT_OFFICIAL_ODDS"]'::jsonb
WHERE odds_snapshot_id IS NULL
   OR break_even_probability IS NULL;

UPDATE model_predictions
SET validation_status = 'invalid',
    validation_errors = validation_errors || '["PROBABILITY_OUT_OF_RANGE"]'::jsonb
WHERE model_probability NOT BETWEEN 0 AND 1
   OR market_probability NOT BETWEEN 0 AND 1;

WITH invalid_markets AS (
    SELECT match_id, model_version_id, play_type, predict_time
    FROM model_predictions
    GROUP BY match_id, model_version_id, play_type, predict_time
    HAVING ABS(SUM(model_probability) - 1.0) > 0.005
        OR ABS(SUM(market_probability) - 1.0) > 0.005
        OR ABS(SUM(model_probability - market_probability)) > 0.005
)
UPDATE model_predictions mp
SET validation_status = 'invalid',
    validation_errors = validation_errors || '["MARKET_PROBABILITY_INTEGRITY"]'::jsonb
FROM invalid_markets bad
WHERE mp.match_id = bad.match_id
  AND mp.model_version_id = bad.model_version_id
  AND mp.play_type = bad.play_type
  AND mp.predict_time = bad.predict_time;

-- Old Elo rows include the pre-fix cold-start and team-order behaviour. They
-- stay queryable for audit, but are excluded from evaluation and decisions.
UPDATE model_predictions mp
SET validation_status = 'invalid',
    validation_errors = validation_errors || '["LEGACY_ELO_NOT_INDEPENDENT"]'::jsonb
FROM model_versions mv
WHERE mv.id = mp.model_version_id
  AND mv.model_name = 'elo_rating'
  AND mp.calculation_version = 'market_metrics_v2_repaired';
