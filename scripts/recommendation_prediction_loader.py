"""Actionable prediction loader for the recommendation agent."""

from __future__ import annotations

from typing import Any


def load_actionable_predictions(conn: Any, model_names: list[str]) -> list[tuple]:
    """Load the latest evidence-complete pre-match prediction per decision key."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_prediction_ids AS (
                SELECT DISTINCT ON (
                    mp.match_id, mp.model_version_id, mp.play_type, mp.option_code
                ) mp.id
                FROM model_predictions mp
                JOIN official_matches m ON m.id = mp.match_id
                JOIN model_versions mv ON mv.id = mp.model_version_id
                WHERE mp.play_type IN ('spf', 'rqspf', 'bf', 'zjq', 'bqc')
                  AND mv.model_name = ANY(%s)
                  AND mv.is_active = true
                  AND mp.odds_snapshot_id IS NOT NULL
                  AND mp.feature_snapshot_id IS NOT NULL
                  AND mp.predict_time < m.kickoff_time
                  AND m.sale_status = 'selling'
                  AND LOWER(COALESCE(m.match_status, ''))
                      IN ('scheduled', 'selling', 'not_started')
                  AND m.kickoff_time > timezone('Asia/Shanghai', NOW())
                  AND (m.sale_stop_time IS NULL
                       OR m.sale_stop_time > timezone('Asia/Shanghai', NOW()))
                ORDER BY mp.match_id, mp.model_version_id, mp.play_type,
                         mp.option_code, mp.predict_time DESC, mp.id DESC
            )
            SELECT
                mp.id, mp.match_id, mp.model_version_id,
                mp.play_type, mp.option_code,
                mp.model_probability, mp.market_probability,
                CASE
                    WHEN latest_os.sp_value > 0
                    THEN mp.model_probability * latest_os.sp_value - 1
                END AS ev,
                mp.confidence_score, mp.risk_score,
                latest_os.id AS odds_snapshot_id, mp.feature_snapshot_id,
                m.home_team_name, m.away_team_name, m.league_name,
                m.kickoff_time,
                COALESCE(latest_os.sp_value, 0) AS sp_value,
                mv.model_name
            FROM latest_prediction_ids latest
            JOIN model_predictions mp ON mp.id = latest.id
            JOIN official_matches m ON m.id = mp.match_id
            JOIN model_versions mv ON mv.id = mp.model_version_id
            LEFT JOIN LATERAL (
                SELECT os.id, os.sp_value
                FROM official_odds_snapshots os
                WHERE os.match_id = mp.match_id
                  AND os.play_type = mp.play_type
                  AND os.option_code = CASE mp.option_code
                      WHEN '3' THEN 'h'
                      WHEN '1' THEN 'd'
                      WHEN '0' THEN 'a'
                      ELSE mp.option_code
                  END
                  AND os.snapshot_time < m.kickoff_time
                ORDER BY os.snapshot_time DESC, os.id DESC
                LIMIT 1
            ) latest_os ON true
            ORDER BY ev DESC NULLS LAST
            """,
            (model_names,),
        )
        return cur.fetchall()
