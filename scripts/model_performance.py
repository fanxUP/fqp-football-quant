"""Model performance history for the user-facing comparison charts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

_PERFORMANCE_HISTORY_SQL = """
    WITH settled_matches AS MATERIALIZED (
        SELECT
            m.id AS match_id,
            m.business_date,
            m.kickoff_time,
            r.spf_result,
            r.rqspf_result,
            r.full_home_goals,
            r.full_away_goals,
            r.total_goals_result,
            r.score_result,
            r.half_full_result
        FROM official_matches m
        JOIN official_results r ON r.match_id = m.id
        WHERE m.business_date >= CURRENT_DATE - %(days)s
          AND r.result_status IN ('final', 'confirmed')
    ),
    normalized_predictions AS (
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
            source_mp.predict_time,
            m.spf_result,
            m.rqspf_result,
            m.full_home_goals,
            m.full_away_goals,
            m.total_goals_result,
            m.score_result,
            m.half_full_result
        FROM model_predictions source_mp
        JOIN model_versions mv ON mv.id = source_mp.model_version_id
        JOIN settled_matches m ON m.match_id = source_mp.match_id
        WHERE source_mp.model_probability IS NOT NULL
          AND source_mp.validation_status = 'valid'
          AND COALESCE(
              (source_mp.uncertainty_reason->>'model_independent')::boolean,
              false
          ) = true
          AND source_mp.predict_time < m.kickoff_time
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
            predict_time,
            spf_result,
            rqspf_result,
            full_home_goals,
            full_away_goals,
            total_goals_result,
            score_result,
            half_full_result
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
    resolved_non_rqspf_picks AS (
        SELECT
            rp.match_id,
            rp.business_date,
            rp.model_name,
            rp.play_type,
            rp.option_code,
            CASE rp.play_type
                WHEN 'spf' THEN rp.spf_result
                WHEN 'zjq' THEN rp.total_goals_result
                WHEN 'bf' THEN rp.score_result
                WHEN 'bqc' THEN REPLACE(rp.half_full_result, '-', '')
            END AS actual_option
        FROM ranked_predictions rp
        WHERE rp.choice_rank = 1
          AND rp.play_type <> 'rqspf'
    ),
    resolved_rqspf_picks AS (
        SELECT
            rp.match_id,
            rp.business_date,
            rp.model_name,
            rp.play_type,
            rp.option_code,
            COALESCE(
                NULLIF(rp.rqspf_result, ''),
                CASE
                    WHEN rq.handicap IS NULL THEN NULL
                    WHEN rp.full_home_goals + rq.handicap > rp.full_away_goals THEN '3'
                    WHEN rp.full_home_goals + rq.handicap = rp.full_away_goals THEN '1'
                    ELSE '0'
                END
            ) AS actual_option
        FROM ranked_predictions rp
        LEFT JOIN LATERAL (
            SELECT odds.handicap
            FROM official_odds_snapshots odds
            WHERE NULLIF(rp.rqspf_result, '') IS NULL
              AND odds.match_id = rp.match_id
              AND odds.play_type = 'rqspf'
              AND odds.handicap IS NOT NULL
            ORDER BY
                ABS(EXTRACT(EPOCH FROM (odds.snapshot_time - rp.predict_time))),
                odds.id DESC
            LIMIT 1
        ) rq ON true
        WHERE rp.choice_rank = 1
          AND rp.play_type = 'rqspf'
    ),
    resolved_picks AS (
        SELECT * FROM resolved_non_rqspf_picks
        UNION ALL
        SELECT * FROM resolved_rqspf_picks
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
    evaluation_scopes AS (
        SELECT
            match_id,
            business_date,
            model_name,
            play_type,
            is_correct
        FROM scored_picks
        UNION ALL
        SELECT
            match_id,
            business_date,
            model_name,
            'all' AS play_type,
            is_correct
        FROM scored_picks
    ),
    scope_summaries AS (
        SELECT
            play_type,
            model_name,
            COUNT(*) AS total_samples,
            COUNT(DISTINCT business_date) AS settled_dates,
            MIN(business_date) AS first_date,
            MAX(business_date) AS last_date
        FROM evaluation_scopes
        GROUP BY play_type, model_name
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
        FROM evaluation_scopes
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
    SELECT
        daily_points.business_date,
        daily_points.play_type,
        daily_points.model_name,
        daily_points.hit_rate,
        daily_points.sample_size,
        scope_summaries.total_samples,
        scope_summaries.settled_dates,
        scope_summaries.first_date,
        scope_summaries.last_date
    FROM daily_points
    JOIN scope_summaries USING (play_type, model_name)
    ORDER BY daily_points.play_type, daily_points.business_date, daily_points.model_name
"""

_PERFORMANCE_HISTORY_FROM_SCORED_PICKS_SQL = """
    WITH scoped_picks AS MATERIALIZED (
        SELECT match_id, business_date, model_name, play_type, is_correct
        FROM model_performance_scored_picks
        WHERE business_date >= CURRENT_DATE - %(days)s
    ),
    evaluation_scopes AS (
        SELECT match_id, business_date, model_name, play_type, is_correct
        FROM scoped_picks
        UNION ALL
        SELECT match_id, business_date, model_name, 'all' AS play_type, is_correct
        FROM scoped_picks
    ),
    scope_summaries AS (
        SELECT
            play_type,
            model_name,
            COUNT(*) AS total_samples,
            COUNT(DISTINCT business_date) AS settled_dates,
            MIN(business_date) AS first_date,
            MAX(business_date) AS last_date
        FROM evaluation_scopes
        GROUP BY play_type, model_name
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
        FROM evaluation_scopes
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
    SELECT
        daily_points.business_date,
        daily_points.play_type,
        daily_points.model_name,
        daily_points.hit_rate,
        daily_points.sample_size,
        scope_summaries.total_samples,
        scope_summaries.settled_dates,
        scope_summaries.first_date,
        scope_summaries.last_date
    FROM daily_points
    JOIN scope_summaries USING (play_type, model_name)
    ORDER BY daily_points.play_type, daily_points.business_date, daily_points.model_name
"""


# Reuse the exact prediction normalization/ranking/scoring CTEs from the
# response query, stopping before its rolling-window aggregation.
_REFRESH_SETTLED_PICKS_SQL = (
    """
    WITH settled_matches AS MATERIALIZED (
        SELECT
            match_id,
            business_date,
            kickoff_time,
            spf_result,
            rqspf_result,
            full_home_goals,
            full_away_goals,
            total_goals_result,
            score_result,
            half_full_result
        FROM model_performance_refresh_settled
    ),
"""
    + _PERFORMANCE_HISTORY_SQL[
        _PERFORMANCE_HISTORY_SQL.index(
            "    normalized_predictions AS ("
        ) : _PERFORMANCE_HISTORY_SQL.index("    evaluation_scopes AS (")
    ]
    .rstrip()
    .removesuffix(",")
    + """
    INSERT INTO model_performance_scored_picks (
        match_id, business_date, model_name, play_type, is_correct, refreshed_at
    )
    SELECT match_id, business_date, model_name, play_type, is_correct, NOW()
    FROM scored_picks
    ON CONFLICT (match_id, model_name, play_type) DO UPDATE SET
        business_date = EXCLUDED.business_date,
        is_correct = EXCLUDED.is_correct,
        refreshed_at = EXCLUDED.refreshed_at
"""
)


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

    return _history_payload(rows, window=window, days=days)


def get_model_performance_history_auto(
    conn: Any,
    *,
    window: int = 20,
    days: int = 365,
) -> dict[str, Any]:
    """Use persisted scored picks when ready, otherwise preserve the full-query fallback."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", ("model_performance_scored_picks_state",))
        state_table = cur.fetchone()[0]
        if state_table is not None:
            cur.execute(
                """
                SELECT
                    full_refreshed_at IS NOT NULL,
                    last_refreshed_at >= NOW() - INTERVAL '2 hours'
                FROM model_performance_scored_picks_state
                WHERE singleton = TRUE
                """
            )
            row = cur.fetchone()
            ready = bool(row and row[0] and row[1])
        else:
            ready = False

        if ready:
            cur.execute(
                _PERFORMANCE_HISTORY_FROM_SCORED_PICKS_SQL,
                {"days": days, "preceding": window - 1},
            )
            rows = cur.fetchall()
        else:
            rows = None

    if rows is None:
        return get_model_performance_history(conn, window=window, days=days)
    return _history_payload(rows, window=window, days=days)


def refresh_model_performance_scored_picks(
    conn: Any,
    *,
    days: int = 1095,
    overlap_days: int = 2,
    force_full: bool = False,
) -> dict[str, Any]:
    """Backfill once, then refresh picks for recently changed official results."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('model_performance_scored_picks') IS NOT NULL
                    AND to_regclass('model_performance_scored_picks_state') IS NOT NULL
                """
            )
            schema_ready = cur.fetchone()
            if not schema_ready or not schema_ready[0]:
                conn.rollback()
                return {"status": "skipped", "reason": "migration_not_applied"}

            cur.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (913201, 103))
            lock_row = cur.fetchone()
            if not lock_row or not lock_row[0]:
                conn.rollback()
                return {"status": "skipped", "reason": "refresh_already_running"}

            cur.execute(
                """
                INSERT INTO model_performance_scored_picks_state (singleton)
                VALUES (TRUE)
                ON CONFLICT (singleton) DO NOTHING
                """
            )
            cur.execute(
                """
                SELECT
                    full_refreshed_at IS NULL
                    OR full_refreshed_at < NOW() - INTERVAL '7 days'
                FROM model_performance_scored_picks_state
                WHERE singleton = TRUE
                FOR UPDATE
                """
            )
            state_row = cur.fetchone()
            full_refresh = force_full or not state_row or bool(state_row[0])

            if full_refresh:
                cur.execute("DELETE FROM model_performance_scored_picks")
                cur.execute(
                    """
                    CREATE TEMP TABLE model_performance_refresh_settled
                    ON COMMIT DROP AS
                    SELECT
                        m.id AS match_id,
                        m.business_date,
                        m.kickoff_time,
                        r.spf_result,
                        r.rqspf_result,
                        r.full_home_goals,
                        r.full_away_goals,
                        r.total_goals_result,
                        r.score_result,
                        r.half_full_result
                    FROM official_matches m
                    JOIN official_results r ON r.match_id = m.id
                    WHERE m.business_date >= CURRENT_DATE - %(days)s
                      AND r.result_status IN ('final', 'confirmed')
                    """,
                    {"days": days},
                )
                cur.execute("SELECT COUNT(*) FROM model_performance_refresh_settled")
                matches_refreshed = int(cur.fetchone()[0])
                refresh_type = "full"
            else:
                cur.execute(
                    """
                    CREATE TEMP TABLE model_performance_refresh_targets
                    ON COMMIT DROP AS
                    SELECT m.id AS match_id
                    FROM official_matches m
                    JOIN official_results r ON r.match_id = m.id
                    WHERE r.updated_at >= NOW() - %(overlap_days)s * INTERVAL '1 day'
                       OR m.updated_at >= NOW() - %(overlap_days)s * INTERVAL '1 day'
                    """,
                    {"overlap_days": overlap_days},
                )
                cur.execute("SELECT COUNT(*) FROM model_performance_refresh_targets")
                matches_refreshed = int(cur.fetchone()[0])
                cur.execute(
                    """
                    DELETE FROM model_performance_scored_picks scored
                    USING model_performance_refresh_targets target
                    WHERE scored.match_id = target.match_id
                    """
                )
                cur.execute(
                    """
                    CREATE TEMP TABLE model_performance_refresh_settled
                    ON COMMIT DROP AS
                    SELECT
                        m.id AS match_id,
                        m.business_date,
                        m.kickoff_time,
                        r.spf_result,
                        r.rqspf_result,
                        r.full_home_goals,
                        r.full_away_goals,
                        r.total_goals_result,
                        r.score_result,
                        r.half_full_result
                    FROM official_matches m
                    JOIN official_results r ON r.match_id = m.id
                    JOIN model_performance_refresh_targets target
                      ON target.match_id = m.id
                    WHERE m.business_date >= CURRENT_DATE - %(days)s
                      AND r.result_status IN ('final', 'confirmed')
                    """,
                    {"days": days},
                )
                refresh_type = "incremental"

            cur.execute(_REFRESH_SETTLED_PICKS_SQL)
            scored_picks_written = max(cur.rowcount, 0)
            cur.execute(
                """
                UPDATE model_performance_scored_picks_state
                SET full_refreshed_at = CASE
                        WHEN %(full_refresh)s THEN NOW()
                        ELSE full_refreshed_at
                    END,
                    last_refreshed_at = NOW()
                WHERE singleton = TRUE
                """,
                {"full_refresh": full_refresh},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "status": "ok",
        "refresh_type": refresh_type,
        "matches_refreshed": matches_refreshed,
        "scored_picks_written": scored_picks_written,
    }


def _history_payload(rows: list[tuple[Any, ...]], *, window: int, days: int) -> dict[str, Any]:

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
    samples_by_scope: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row[1]), str(row[2]))
        samples_by_scope[key] = {
            "play_type": row[1],
            "model_name": row[2],
            "total_samples": int(row[5]),
            "settled_dates": int(row[6]),
            "first_date": _iso_date(row[7]),
            "last_date": _iso_date(row[8]),
        }

    return {
        "status": "ok",
        "metric": "rolling_hit_rate",
        "window": window,
        "days": days,
        "points": points,
        "samples": list(samples_by_scope.values()),
    }
