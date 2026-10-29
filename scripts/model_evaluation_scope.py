"""Canonical independent-sample scope shared by model evaluation queries.

Model versions are implementation snapshots, not new independent observations.
Every settled match is therefore counted at most once per logical model name.
"""

from scripts.prediction_statistics import canonical_prediction_rows_ctes

MODEL_PRELIMINARY_MIN_SAMPLES = 30
MODEL_PUBLICATION_MIN_SAMPLES = 100


def model_sample_status(sample_count: int) -> str:
    if sample_count >= MODEL_PUBLICATION_MIN_SAMPLES:
        return "qualified"
    if sample_count >= MODEL_PRELIMINARY_MIN_SAMPLES:
        return "preliminary"
    return "monitoring"


LATEST_METRICS_CTE = """
    WITH RECURSIVE metric_keys AS (
        (
            SELECT match_id, model_version_id
            FROM market_efficiency_metrics
            WHERE play_type = 'spf' AND brier_score IS NOT NULL
              AND model_version_id IS NOT NULL
            ORDER BY match_id, model_version_id LIMIT 1
        )
        UNION ALL
        SELECT next_key.* FROM metric_keys previous
        CROSS JOIN LATERAL (
            SELECT match_id, model_version_id
            FROM market_efficiency_metrics
            WHERE play_type = 'spf' AND brier_score IS NOT NULL
              AND model_version_id IS NOT NULL
              AND (match_id, model_version_id)
                  > (previous.match_id, previous.model_version_id)
            ORDER BY match_id, model_version_id LIMIT 1
        ) next_key
    ), metrics_by_version AS (
        -- Apply eligibility before choosing a version's latest score, matching
        -- the historical evaluation scope (including its null-score fallback).
        SELECT source_mem.* FROM metric_keys keys
        JOIN official_matches source_match ON source_match.id = keys.match_id
        JOIN official_results source_result ON source_result.match_id = keys.match_id
        CROSS JOIN LATERAL (
            SELECT source_mem.* FROM market_efficiency_metrics source_mem
            WHERE source_mem.match_id = keys.match_id
              AND source_mem.model_version_id = keys.model_version_id
              AND source_mem.model_version_id IS NOT NULL
              AND source_mem.brier_score IS NOT NULL
              AND source_mem.play_type = 'spf'
              AND source_mem.snapshot_time < source_match.kickoff_time
            ORDER BY source_mem.snapshot_time DESC, source_mem.id DESC LIMIT 1
        ) source_mem
        WHERE source_result.result_status IN ('final', 'confirmed')
    ), latest_metrics AS (
        SELECT DISTINCT ON (source_mem.match_id, source_mv.model_name)
            source_mem.*,
            source_mv.model_name AS canonical_model_name
        FROM metrics_by_version source_mem
        JOIN model_versions source_mv ON source_mv.id = source_mem.model_version_id
        ORDER BY source_mem.match_id,
                 source_mv.model_name,
                 source_mem.snapshot_time DESC,
                 source_mem.id DESC
    )
"""


def _metric_prediction_rows_ctes() -> str:
    return f"""
        , metric_prediction_matches AS MATERIALIZED (
            SELECT DISTINCT match_id FROM latest_metrics
        ), {canonical_prediction_rows_ctes(match_scope="metric_prediction_matches", spf_only=True)}
    """


METRIC_HOME_PREDICTIONS_CTE = """
    , metric_home_predictions AS (
        -- This small, option-scoped compatibility read already pushes the
        -- match/option predicate ahead of the view's legacy ranking.
        -- Do not filter version/time here: a newer version or timestamp must
        -- still shield an older row that matched the evaluation snapshot.
        SELECT latest.* FROM model_prediction_latest_rows latest
        WHERE latest.match_id = ANY(ARRAY(SELECT match_id FROM latest_metrics))
          AND latest.play_type = 'spf' AND latest.option_code = '3'
    )
"""


EVALUATION_PREDICTION_ROWS_CTES = f"""
    WITH RECURSIVE evaluation_matches AS MATERIALIZED (
        SELECT DISTINCT m.id AS match_id FROM official_matches m
        JOIN official_results r ON r.match_id = m.id
        WHERE r.result_status IN ('final', 'confirmed')
    ), {canonical_prediction_rows_ctes(match_scope="evaluation_matches")},
    evaluation_prediction_rows AS (
        -- Reuse the canonical seek boundary, including invalid/latest rows and
        -- complete-group precedence. Apply evaluation eligibility afterwards.
        SELECT * FROM canonical_prediction_rows
    )
"""


LATEST_PREDICTIONS_CTE = (
    EVALUATION_PREDICTION_ROWS_CTES
    + """
    , latest_predictions AS (
        SELECT DISTINCT ON (
            source_mp.match_id,
            source_mv.model_name,
            source_mp.play_type,
            source_mp.option_code
        ) source_mp.*,
          source_mv.model_name AS canonical_model_name
        FROM evaluation_prediction_rows source_mp
        JOIN model_versions source_mv ON source_mv.id = source_mp.model_version_id
        JOIN official_matches source_match ON source_match.id = source_mp.match_id
        JOIN official_results source_result ON source_result.match_id = source_mp.match_id
        WHERE source_mp.predict_time < source_match.kickoff_time
          AND source_mp.validation_status = 'valid'
          AND COALESCE(
              (source_mp.uncertainty_reason->>'model_independent')::boolean,
              false
          ) = true
          AND source_result.result_status IN ('final', 'confirmed')
        ORDER BY source_mp.match_id,
                 source_mv.model_name,
                 source_mp.play_type,
                 source_mp.option_code,
                 source_mp.predict_time DESC,
                 source_mp.id DESC
    )
"""
)


SETTLED_SPF_RESULTS_CTE = """
    , scored_spf_results AS (
        SELECT r.match_id, r.spf_result,
               CASE
                   WHEN r.full_home_goals > r.full_away_goals THEN '3'
                   WHEN r.full_home_goals = r.full_away_goals THEN '1'
                   ELSE '0'
               END AS actual_result
        FROM official_results r
        WHERE r.result_status IN ('final', 'confirmed')
          AND r.full_home_goals >= 0 AND r.full_away_goals >= 0
    ), settled_spf_results AS (
        -- A complete score can supply missing SPF, but cannot resolve a
        -- contradictory or invalid code without verifying the source.
        SELECT match_id, actual_result FROM scored_spf_results
        WHERE spf_result IS NULL OR spf_result = actual_result
    )
"""


CALIBRATION_PREDICTIONS_CTE = (
    LATEST_PREDICTIONS_CTE
    + SETTLED_SPF_RESULTS_CTE
    + """
    , calibration_predictions AS (
        SELECT mp.*, m.kickoff_time, r.actual_result
        FROM latest_predictions mp
        JOIN official_matches m ON m.id = mp.match_id
        JOIN settled_spf_results r ON r.match_id = mp.match_id
        WHERE mp.play_type = 'spf'
          AND mp.option_code IN ('3', '1', '0')
          AND mp.model_probability IS NOT NULL
    )
"""
)


MARKET_BASELINE_BRIER_CTES = (
    _metric_prediction_rows_ctes()
    + """
    , latest_market_baseline_predictions AS (
        SELECT DISTINCT ON (source_mp.match_id, source_mp.option_code)
            source_mp.match_id,
            source_mp.option_code,
            source_mp.model_probability
        FROM (
            -- Only these matches can be paired with an evaluated model.
            -- Their canonical rows were sought before evaluation eligibility.
            SELECT latest.* FROM canonical_prediction_rows latest
        ) source_mp
        JOIN model_versions source_mv ON source_mv.id = source_mp.model_version_id
        JOIN official_matches source_match ON source_match.id = source_mp.match_id
        JOIN official_results source_result ON source_result.match_id = source_mp.match_id
        WHERE source_mv.model_name = 'market_baseline'
          AND source_mp.play_type = 'spf'
          AND source_mp.model_probability IS NOT NULL
          AND source_mp.validation_status = 'valid'
          AND source_mp.predict_time < source_match.kickoff_time
          AND source_result.result_status IN ('final', 'confirmed')
        ORDER BY source_mp.match_id,
                 source_mp.option_code,
                 source_mp.predict_time DESC,
                 source_mp.id DESC
    ), market_baseline_scores AS (
        SELECT
            source_mp.match_id,
            SUM(POWER(
                source_mp.model_probability - CASE
                    WHEN source_mp.option_code = source_result.spf_result THEN 1
                    ELSE 0
                END,
                2
            )) AS brier_score
        FROM latest_market_baseline_predictions source_mp
        JOIN official_results source_result ON source_result.match_id = source_mp.match_id
        WHERE source_result.spf_result IN ('3', '1', '0')
        GROUP BY source_mp.match_id
        HAVING COUNT(DISTINCT source_mp.option_code) = 3
    )
"""
)
