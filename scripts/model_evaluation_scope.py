"""Canonical independent-sample scope shared by model evaluation queries.

Model versions are implementation snapshots, not new independent observations.
Every settled match is therefore counted at most once per logical model name.
"""

MODEL_PRELIMINARY_MIN_SAMPLES = 30
MODEL_PUBLICATION_MIN_SAMPLES = 100


def model_sample_status(sample_count: int) -> str:
    if sample_count >= MODEL_PUBLICATION_MIN_SAMPLES:
        return "qualified"
    if sample_count >= MODEL_PRELIMINARY_MIN_SAMPLES:
        return "preliminary"
    return "monitoring"


LATEST_METRICS_CTE = """
    WITH latest_metrics AS (
        SELECT DISTINCT ON (source_mem.match_id, source_mv.model_name)
            source_mem.*,
            source_mv.model_name AS canonical_model_name
        FROM market_efficiency_metrics source_mem
        JOIN model_versions source_mv ON source_mv.id = source_mem.model_version_id
        JOIN official_matches source_match ON source_match.id = source_mem.match_id
        JOIN official_results source_result ON source_result.match_id = source_mem.match_id
        WHERE source_mem.brier_score IS NOT NULL
          AND source_mem.play_type = 'spf'
          AND source_mem.snapshot_time < source_match.kickoff_time
          AND source_result.result_status IN ('final', 'confirmed')
        ORDER BY source_mem.match_id,
                 source_mv.model_name,
                 source_mem.snapshot_time DESC,
                 source_mem.id DESC
    )
"""


LATEST_PREDICTIONS_CTE = """
    WITH latest_predictions AS (
        SELECT DISTINCT ON (
            source_mp.match_id,
            source_mv.model_name,
            source_mp.play_type,
            source_mp.option_code
        ) source_mp.*,
          source_mv.model_name AS canonical_model_name
        FROM model_predictions source_mp
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


MARKET_BASELINE_BRIER_CTES = """
    , latest_market_baseline_predictions AS (
        SELECT DISTINCT ON (source_mp.match_id, source_mp.option_code)
            source_mp.match_id,
            source_mp.option_code,
            source_mp.model_probability
        FROM model_predictions source_mp
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
