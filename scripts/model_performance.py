"""Model performance history for the user-facing comparison charts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

_PERFORMANCE_HISTORY_SQL = """
    WITH normalized_predictions AS (
        SELECT
            source_mp.id AS prediction_id,
            source_mp.match_id,
            m.business_date,
            mv.model_name,
            CASE source_mp.play_type
                WHEN 'score' THEN 'bf'
                WHEN 'total_goals' THEN 'zjq'
                WHEN 'half_full' THEN 'bqc'
                ELSE source_mp.play_type
            END AS play_type,
            source_mp.option_code,
            source_mp.model_probability,
            source_mp.predict_time
        FROM model_predictions source_mp
        JOIN model_versions mv ON mv.id = source_mp.model_version_id
        JOIN official_matches m ON m.id = source_mp.match_id
        WHERE source_mp.model_probability IS NOT NULL
          AND m.business_date >= CURRENT_DATE - %(days)s
          AND source_mp.play_type IN (
              'spf', 'rqspf', 'bf', 'score',
              'zjq', 'total_goals', 'bqc', 'half_full'
          )
    ),
    latest_predictions AS (
        SELECT DISTINCT ON (match_id, model_name, play_type, option_code)
            prediction_id,
            match_id,
            business_date,
            model_name,
            play_type,
            option_code,
            model_probability,
            predict_time
        FROM normalized_predictions
        ORDER BY
            match_id, model_name, play_type, option_code,
            predict_time DESC, prediction_id DESC
    ),
    ranked_predictions AS (
        SELECT
            latest_predictions.*,
            ROW_NUMBER() OVER (
                PARTITION BY match_id, model_name, play_type
                ORDER BY model_probability DESC, option_code
            ) AS choice_rank
        FROM latest_predictions
    ),
    resolved_picks AS (
        SELECT
            rp.match_id,
            rp.business_date,
            rp.model_name,
            rp.play_type,
            rp.option_code,
            CASE
                WHEN rp.play_type = 'spf' THEN r.spf_result
                WHEN rp.play_type = 'rqspf' THEN COALESCE(
                    NULLIF(r.rqspf_result, ''),
                    CASE
                        WHEN rq.handicap IS NULL THEN NULL
                        WHEN r.full_home_goals + rq.handicap > r.full_away_goals THEN '3'
                        WHEN r.full_home_goals + rq.handicap = r.full_away_goals THEN '1'
                        ELSE '0'
                    END
                )
                WHEN rp.play_type = 'zjq' THEN r.total_goals_result
                WHEN rp.play_type = 'bf' THEN r.score_result
                WHEN rp.play_type = 'bqc' THEN REPLACE(r.half_full_result, '-', '')
            END AS actual_option
        FROM ranked_predictions rp
        JOIN official_results r ON r.match_id = rp.match_id
        LEFT JOIN LATERAL (
            SELECT odds.handicap
            FROM official_odds_snapshots odds
            WHERE odds.match_id = rp.match_id
              AND odds.play_type = 'rqspf'
              AND odds.handicap IS NOT NULL
            ORDER BY
                ABS(EXTRACT(EPOCH FROM (odds.snapshot_time - rp.predict_time))),
                odds.id DESC
            LIMIT 1
        ) rq ON rp.play_type = 'rqspf'
        WHERE rp.choice_rank = 1
          AND r.result_status IN ('final', 'confirmed')
    ),
    scored_picks AS (
        SELECT
            match_id,
            business_date,
            model_name,
            play_type,
            (option_code = actual_option)::int AS is_correct
        FROM resolved_picks
        WHERE actual_option IS NOT NULL AND actual_option <> ''
    ),
    rolling_scores AS (
        SELECT
            match_id,
            business_date,
            model_name,
            play_type,
            AVG(is_correct::numeric) OVER (
                PARTITION BY play_type, model_name
                ORDER BY business_date, match_id
                ROWS BETWEEN %(preceding)s PRECEDING AND CURRENT ROW
            ) AS hit_rate,
            COUNT(*) OVER (
                PARTITION BY play_type, model_name
                ORDER BY business_date, match_id
                ROWS BETWEEN %(preceding)s PRECEDING AND CURRENT ROW
            ) AS sample_size
        FROM scored_picks
    ),
    daily_points AS (
        SELECT DISTINCT ON (play_type, model_name, business_date)
            business_date,
            play_type,
            model_name,
            hit_rate,
            sample_size
        FROM rolling_scores
        ORDER BY play_type, model_name, business_date, match_id DESC
    )
    SELECT business_date, play_type, model_name, hit_rate, sample_size
    FROM daily_points
    ORDER BY play_type, business_date, model_name
"""


def _iso_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def get_model_performance_history(
    conn: Any,
    *,
    window: int = 20,
    days: int = 365,
) -> dict[str, Any]:
    """Return rolling top-pick hit rates by date, play type and model."""
    with conn.cursor() as cur:
        cur.execute(
            _PERFORMANCE_HISTORY_SQL,
            {"days": days, "preceding": window - 1},
        )
        rows = cur.fetchall()

    points = [
        {
            "date": _iso_date(row[0]),
            "play_type": row[1],
            "model_name": row[2],
            "hit_rate": round(float(row[3]), 4),
            "sample_size": int(row[4]),
        }
        for row in rows
    ]
    return {
        "status": "ok",
        "metric": "rolling_hit_rate",
        "window": window,
        "points": points,
    }
