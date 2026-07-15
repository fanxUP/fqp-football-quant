-- Remove derived error rows that were created from post-kickoff or non-top SPF options.
WITH latest_options AS (
    SELECT DISTINCT ON (mp.match_id, mp.model_version_id, mp.option_code)
        mp.id,
        mp.match_id,
        mp.model_version_id,
        mp.option_code,
        mp.model_probability
    FROM model_predictions mp
    JOIN official_matches m ON m.id = mp.match_id
    JOIN official_results r ON r.match_id = mp.match_id
    WHERE mp.play_type = 'spf'
      AND mp.option_code IN ('3', '1', '0')
      AND mp.model_probability IS NOT NULL
      AND mp.predict_time < m.kickoff_time
      AND r.result_status IN ('final', 'confirmed')
      AND r.spf_result IS NOT NULL
    ORDER BY mp.match_id, mp.model_version_id, mp.option_code,
             mp.predict_time DESC, mp.id DESC
), top_picks AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY match_id, model_version_id
               ORDER BY model_probability DESC NULLS LAST, option_code, id DESC
           ) AS pick_rank
    FROM latest_options
)
DELETE FROM prediction_error_analysis pea
WHERE pea.prediction_id IS NULL
   OR NOT EXISTS (
       SELECT 1
       FROM top_picks tp
       WHERE tp.id = pea.prediction_id AND tp.pick_rank = 1
   );

CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_error_analysis_prediction
    ON prediction_error_analysis(prediction_id)
    WHERE prediction_id IS NOT NULL;

-- Reconcile historical review counters with the same pre-match boundary.
UPDATE daily_reviews dr
SET analyzable_match_count = (
        SELECT COUNT(DISTINCT fs.match_id)
        FROM match_feature_snapshots fs
        JOIN official_matches m ON m.id = fs.match_id
        WHERE m.business_date = dr.review_date
          AND fs.snapshot_time < m.kickoff_time
    ),
    recommended_match_count = (
        SELECT COUNT(DISTINCT mp.match_id)
        FROM model_predictions mp
        JOIN official_matches m ON m.id = mp.match_id
        WHERE m.business_date = dr.review_date
          AND mp.predict_time < m.kickoff_time
    );
