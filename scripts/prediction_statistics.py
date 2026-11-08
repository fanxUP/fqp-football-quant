"""Prediction read scopes and exact scheduled historical count snapshots."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agent_storage import finish_job_run, start_job_run

JOB_CODE = "refresh_prediction_count"
COUNT_SCOPE = "valid_prematch_history_v1"
PREDICTION_SUMMARY_SCOPE = "canonical_valid_prematch_history_v1"
MAX_AGE = timedelta(minutes=45)
# Production canceled a canonical rollup for a five-match chunk; isolate each
# match so one heavy fixture does not roll back the other matches in its chunk.
DEFAULT_REFRESH_BATCH_SIZE = 1
MAX_SCHEDULED_REFRESH_BATCH_SIZE = 5
MAX_REFRESH_BATCH_SIZE = 1000
MAX_REFRESH_BATCHES_PER_RUN = 20
CLAIM_STATEMENT_TIMEOUT_SECONDS = 5
ORPHAN_DELETE_STATEMENT_TIMEOUT_SECONDS = 5
ROLLUP_STATEMENT_TIMEOUT_SECONDS = 25
SNAPSHOT_STATEMENT_TIMEOUT_SECONDS = 10
REFRESH_BATCH_SQL_RESERVATION_SECONDS = 50
# Normal starts at :18/:48 ahead of long :20/:50 work; catch-up slots are
# two minutes apart. Keep a nominal 30-second gap after the SQL work budget.
REFRESH_RUN_SQL_BUDGET_SECONDS = 90


def latest_prediction_ctes(
    *,
    filter_match: bool,
    filter_match_ids: bool = False,
    match_scope: str | None = None,
    spf_only: bool = False,
    spf_home_only: bool = False,
    legacy_strategy: str = "recursive",
) -> str:
    """Select canonical prediction rows with a bounded legacy access strategy."""
    if spf_home_only and not spf_only:
        raise ValueError("spf_home_only requires spf_only")
    if legacy_strategy not in {"recursive", "scoped_scan"}:
        raise ValueError("legacy_strategy must be recursive or scoped_scan")
    group_match = "AND g.match_id = %(match_id)s" if filter_match else ""
    key_match = "WHERE p.match_id = %(match_id)s" if filter_match else ""
    next_match = "AND p.match_id = %(match_id)s" if filter_match else ""
    play_filter = "AND p.play_type = 'spf'" if spf_only else ""
    option_filter = "AND p.option_code = '3'" if spf_home_only else ""
    option_keys_cte = (
        "option_keys AS (SELECT '3'::text AS option_code)"
        if spf_home_only
        else """
            option_keys AS (
                (
                    SELECT p.option_code FROM model_predictions p
                    WHERE p.match_id = keys.match_id
                      AND p.model_version_id = keys.model_version_id
                      AND p.play_type = keys.play_type
                    ORDER BY p.option_code LIMIT 1
                )
                UNION ALL
                SELECT next_option.* FROM option_keys previous_option
                CROSS JOIN LATERAL (
                    SELECT p.option_code FROM model_predictions p
                    WHERE p.match_id = keys.match_id
                      AND p.model_version_id = keys.model_version_id
                      AND p.play_type = keys.play_type
                      AND p.option_code > previous_option.option_code
                    ORDER BY p.option_code LIMIT 1
                ) next_option
            )
        """
    )
    if filter_match_ids:
        group_match = "AND g.match_id = ANY(%(match_ids)s::bigint[])"
        key_match = "WHERE p.match_id = ANY(%(match_ids)s::bigint[])"
        next_match = "AND p.match_id = ANY(%(match_ids)s::bigint[])"
    if legacy_strategy == "scoped_scan":
        if (
            match_scope is None
            or filter_match
            or filter_match_ids
            or not re.fullmatch(r"[a-z_][a-z_0-9]*", match_scope)
        ):
            raise ValueError("scoped_scan requires a static match_scope")
        group_match = f"AND g.match_id = ANY(ARRAY(SELECT match_id FROM {match_scope}))"
        candidate_filters = []
        if spf_only:
            candidate_filters.append("p.play_type = 'spf'")
        if spf_home_only:
            candidate_filters.append("p.option_code = '3'")
        candidate_filter_sql = " AND ".join(candidate_filters)
        if candidate_filter_sql:
            candidate_filter_sql += " AND "
        return f"""
            latest_groups AS MATERIALIZED (
                SELECT DISTINCT ON (g.match_id, mv.model_name, g.play_type)
                    g.id AS group_id, g.match_id, mv.model_name, g.play_type
                FROM model_prediction_groups g
                JOIN model_prediction_runs r ON r.id = g.run_id
                JOIN model_versions mv ON mv.id = g.model_version_id
                WHERE g.group_status = 'complete'
                  AND r.run_status IN ('completed', 'partial')
                  {group_match}
                  {"AND g.play_type = 'spf'" if spf_only else ""}
                ORDER BY g.match_id, mv.model_name, g.play_type,
                         g.predict_time DESC, g.created_at DESC, g.id DESC
            ), legacy_candidates AS MATERIALIZED (
                SELECT p.*, mv.model_name
                FROM {match_scope} scoped
                CROSS JOIN LATERAL (
                    SELECT p.* FROM model_predictions p
                    WHERE p.match_id = scoped.match_id
                    OFFSET 0
                ) p
                JOIN model_versions mv ON mv.id = p.model_version_id
                JOIN official_matches m ON m.id = p.match_id
                WHERE {candidate_filter_sql}NOT EXISTS (
                      SELECT 1 FROM latest_groups g
                      WHERE g.match_id = p.match_id
                        AND g.model_name = mv.model_name
                        AND g.play_type = p.play_type
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM model_prediction_group_options mapped
                      WHERE mapped.prediction_id = p.id
                  )
            ), legacy_latest AS (
                SELECT DISTINCT ON (match_id, model_name, play_type, option_code) *
                FROM legacy_candidates
                ORDER BY match_id, model_name, play_type, option_code,
                         predict_time DESC, id DESC
            )
        """
    key_filters = f"{play_filter} {option_filter}".strip()
    if key_filters:
        key_match = f"{key_match} {key_filters}" if key_match else "WHERE " + key_filters[4:]
    legacy_keys = f"""
        legacy_keys AS (
            (
                SELECT p.match_id, p.model_version_id, p.play_type
                FROM model_predictions p {key_match}
                ORDER BY p.match_id, p.model_version_id, p.play_type LIMIT 1
            )
            UNION ALL
            SELECT next_key.* FROM legacy_keys previous
            CROSS JOIN LATERAL (
                SELECT p.match_id, p.model_version_id, p.play_type
                FROM model_predictions p
                WHERE (p.match_id, p.model_version_id, p.play_type)
                    > (previous.match_id, previous.model_version_id, previous.play_type)
                  {next_match}
                  {play_filter}
                  {option_filter}
                ORDER BY p.match_id, p.model_version_id, p.play_type LIMIT 1
            ) next_key
        )
    """
    if match_scope is not None:
        if filter_match or filter_match_ids or not re.fullmatch(r"[a-z_][a-z_0-9]*", match_scope):
            raise ValueError("match_scope must be a static CTE name and cannot combine filters")
        group_match = f"AND g.match_id = ANY(ARRAY(SELECT match_id FROM {match_scope}))"
        # Seek inside each match's identity index. A global recursive seek with
        # an IN filter can walk unrelated histories between successive keys.
        legacy_keys = f"""
            legacy_keys AS (
                SELECT scoped.match_id, keys.model_version_id, keys.play_type
                FROM {match_scope} scoped
                CROSS JOIN LATERAL (
                    WITH RECURSIVE match_keys AS (
                        (
                            SELECT p.model_version_id, p.play_type
                            FROM model_predictions p WHERE p.match_id = scoped.match_id
                              {play_filter}
                              {option_filter}
                            ORDER BY p.model_version_id, p.play_type LIMIT 1
                        )
                        UNION ALL
                        SELECT next_key.* FROM match_keys previous
                        CROSS JOIN LATERAL (
                            SELECT p.model_version_id, p.play_type FROM model_predictions p
                            WHERE p.match_id = scoped.match_id
                              {play_filter}
                              {option_filter}
                              AND (p.model_version_id, p.play_type)
                                  > (previous.model_version_id, previous.play_type)
                            ORDER BY p.model_version_id, p.play_type LIMIT 1
                        ) next_key
                    ) SELECT * FROM match_keys
                ) keys
            )
        """
    return f"""
        latest_groups AS MATERIALIZED (
            SELECT DISTINCT ON (g.match_id, mv.model_name, g.play_type)
                g.id AS group_id, g.match_id, mv.model_name, g.play_type
            FROM model_prediction_groups g
            JOIN model_prediction_runs r ON r.id = g.run_id
            JOIN model_versions mv ON mv.id = g.model_version_id
            WHERE g.group_status = 'complete'
              AND r.run_status IN ('completed', 'partial')
              {group_match}
              {"AND g.play_type = 'spf'" if spf_only else ""}
            ORDER BY g.match_id, mv.model_name, g.play_type,
                     g.predict_time DESC, g.created_at DESC, g.id DESC
        ), {legacy_keys}, eligible_legacy_keys AS MATERIALIZED (
            SELECT keys.*, mv.model_name FROM legacy_keys keys
            JOIN model_versions mv ON mv.id = keys.model_version_id
            JOIN official_matches m ON m.id = keys.match_id
            WHERE NOT EXISTS (
                SELECT 1 FROM latest_groups g
                WHERE g.match_id = keys.match_id AND g.model_name = mv.model_name
                  AND g.play_type = keys.play_type
            )
        ), legacy_by_version AS (
            SELECT p.*, keys.model_name FROM eligible_legacy_keys keys
            CROSS JOIN LATERAL (
                WITH RECURSIVE {option_keys_cte}
                SELECT p.* FROM option_keys option_key
                CROSS JOIN LATERAL (
                    SELECT p.* FROM model_predictions p
                    WHERE p.match_id = keys.match_id
                      AND p.model_version_id = keys.model_version_id
                      AND p.play_type = keys.play_type
                      AND p.option_code = option_key.option_code
                      AND NOT EXISTS (
                          SELECT 1 FROM model_prediction_group_options mapped
                          WHERE mapped.prediction_id = p.id
                      )
                    ORDER BY p.predict_time DESC, p.id DESC LIMIT 1
                ) p
            ) p
        ), legacy_latest AS (
            SELECT DISTINCT ON (match_id, model_name, play_type, option_code) *
            FROM legacy_by_version
            ORDER BY match_id, model_name, play_type, option_code, predict_time DESC, id DESC
        )
    """


def canonical_prediction_rows_ctes(
    *,
    match_scope: str | None = None,
    spf_only: bool = False,
    spf_home_only: bool = False,
    prefix: str = "",
    legacy_strategy: str = "recursive",
) -> str:
    """Canonical IDs before validity/time filters; preserve complete-group shielding."""
    result = f"""
        {latest_prediction_ctes(filter_match=False, match_scope=match_scope, spf_only=spf_only, spf_home_only=spf_home_only, legacy_strategy=legacy_strategy)},
        canonical_prediction_ids AS (
            SELECT mapped.prediction_id AS id FROM latest_groups groups
            JOIN model_prediction_group_options mapped ON mapped.group_id = groups.group_id
            {"WHERE mapped.option_code = '3'" if spf_home_only else ""}
            UNION ALL
            SELECT id FROM legacy_latest
        ), canonical_prediction_rows AS (
            SELECT mp.* FROM canonical_prediction_ids latest
            JOIN LATERAL (
                SELECT p.* FROM model_predictions p WHERE p.id = latest.id OFFSET 0
            ) mp ON true
        )
    """
    if prefix:
        if not re.fullmatch(r"[a-z_]+", prefix):
            raise ValueError("prefix must be a static SQL identifier prefix")
        names = (
            "latest_groups",
            "legacy_candidates",
            "legacy_keys",
            "eligible_legacy_keys",
            "legacy_by_version",
            "legacy_latest",
            "canonical_prediction_ids",
            "canonical_prediction_rows",
        )
        result = re.sub(r"\b(" + "|".join(names) + r")\b", lambda m: prefix + m[0], result)
    return result


def recent_prediction_rows_ctes() -> str:
    """Exact recent list with a cheap candidate search and a proven fallback.

    A raw valid/prematch row is only a match candidate, never a chosen forecast.
    All states/versions/groups within that match still participate in canonical
    selection. If omitted matches could outrank the last result, read the full
    match scope in the same SQL snapshot instead of returning a partial list.
    """
    return f"""
        WITH RECURSIVE recent_seed AS MATERIALIZED (
            SELECT p.match_id, p.predict_time, p.ev, p.id
            FROM model_predictions p
            JOIN official_matches m ON m.id = p.match_id
            WHERE p.validation_status = 'valid' AND p.predict_time < m.kickoff_time
            ORDER BY p.predict_time DESC, p.ev DESC, p.id DESC LIMIT %(seed_limit)s
        ), recent_match_scope AS MATERIALIZED (
            SELECT DISTINCT match_id FROM recent_seed
        ), {canonical_prediction_rows_ctes(match_scope="recent_match_scope", prefix="fast_")},
        fast_recent AS MATERIALIZED (
            SELECT mp.* FROM fast_canonical_prediction_rows mp
            JOIN official_matches m ON m.id = mp.match_id
            WHERE mp.validation_status = 'valid' AND mp.predict_time < m.kickoff_time
            ORDER BY mp.predict_time DESC, mp.ev DESC, mp.id DESC LIMIT %(limit)s
        ), read_boundary AS MATERIALIZED (
            SELECT (SELECT COUNT(*) FROM recent_seed) < %(seed_limit)s
                OR ((SELECT COUNT(*) FROM fast_recent) = %(limit)s AND COALESCE((
                    SELECT (last_row.predict_time, last_row.ev IS NULL,
                            COALESCE(last_row.ev, 0), last_row.id)
                        >= (frontier.predict_time, frontier.ev IS NULL,
                            COALESCE(frontier.ev, 0), frontier.id)
                    FROM (
                        SELECT * FROM fast_recent
                        ORDER BY predict_time, ev ASC NULLS LAST, id LIMIT 1
                    ) last_row CROSS JOIN (
                        SELECT * FROM recent_seed
                        ORDER BY predict_time, ev ASC NULLS LAST, id LIMIT 1
                    ) frontier
                ), false)) AS complete
        ), fallback_match_scope AS MATERIALIZED (
            SELECT id AS match_id FROM official_matches
            WHERE NOT (SELECT complete FROM read_boundary)
        ), {canonical_prediction_rows_ctes(match_scope="fallback_match_scope", prefix="fallback_")},
        recent AS MATERIALIZED (
            SELECT * FROM fast_recent WHERE (SELECT complete FROM read_boundary)
            UNION ALL
            (SELECT mp.* FROM fallback_canonical_prediction_rows mp
             JOIN official_matches m ON m.id = mp.match_id
             WHERE mp.validation_status = 'valid' AND mp.predict_time < m.kickoff_time
             ORDER BY mp.predict_time DESC, mp.ev DESC, mp.id DESC LIMIT %(limit)s)
        )
    """


def compute_prediction_count(conn: Any) -> dict[str, Any]:
    """Count all eligible historical rows at one database statement snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*), statement_timestamp(), clock_timestamp()
               FROM model_predictions mp
               JOIN model_versions mv ON mv.id = mp.model_version_id
               JOIN official_matches m ON m.id = mp.match_id
               WHERE mp.validation_status = 'valid'
                 AND mp.predict_time < m.kickoff_time"""
        )
        total, data_as_of, computed_at = cur.fetchone()
    return {
        "scope": COUNT_SCOPE,
        "total": int(total),
        "data_as_of": data_as_of.astimezone(UTC).isoformat(),
        "computed_at": computed_at.astimezone(UTC).isoformat(),
    }


def compute_prediction_snapshots(conn: Any) -> dict[str, dict[str, Any]]:
    """Compute the legacy dashboard count and exact canonical API summary together."""
    latest_ctes = latest_prediction_ctes(filter_match=False)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL jit = off")
        cur.execute(
            f"""
            WITH RECURSIVE {latest_ctes}, latest_ids AS (
                SELECT mapped.prediction_id AS id FROM latest_groups groups
                JOIN model_prediction_group_options mapped ON mapped.group_id = groups.group_id
                UNION ALL
                SELECT id FROM legacy_latest
            ), summary_snapshot AS MATERIALIZED (
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE mp.ev > 0) AS positive_ev_count,
                    AVG(mp.confidence_score) AS avg_confidence,
                    COUNT(DISTINCT mv.model_name) AS model_count,
                    MAX(mp.predict_time) AS latest_predict_time
                FROM latest_ids latest
                JOIN LATERAL (
                    SELECT p.* FROM model_predictions p WHERE p.id = latest.id OFFSET 0
                ) mp ON true
                JOIN model_versions mv ON mv.id = mp.model_version_id
                JOIN official_matches m ON m.id = mp.match_id
                WHERE mp.validation_status = 'valid'
                  AND mp.predict_time < m.kickoff_time
            ), prediction_count_snapshot AS MATERIALIZED (
                SELECT COUNT(*) AS total
                FROM model_predictions mp
                JOIN model_versions mv ON mv.id = mp.model_version_id
                JOIN official_matches m ON m.id = mp.match_id
                WHERE mp.validation_status = 'valid'
                  AND mp.predict_time < m.kickoff_time
            )
            SELECT summary_snapshot.total,
                   summary_snapshot.positive_ev_count,
                   summary_snapshot.avg_confidence,
                   summary_snapshot.model_count,
                   summary_snapshot.latest_predict_time,
                   prediction_count_snapshot.total,
                   statement_timestamp(),
                   clock_timestamp()
            FROM summary_snapshot CROSS JOIN prediction_count_snapshot
            """
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("prediction summary query returned no row")
    (
        summary_total,
        positive_ev,
        confidence,
        model_count,
        latest_time,
        raw_total,
        data_as_of,
        computed_at,
    ) = row
    data_as_of = data_as_of.astimezone(UTC).isoformat()
    computed_at = computed_at.astimezone(UTC).isoformat()
    return {
        "prediction_count": {
            "scope": COUNT_SCOPE,
            "total": int(raw_total),
            "data_as_of": data_as_of,
            "computed_at": computed_at,
        },
        "prediction_summary": {
            "scope": PREDICTION_SUMMARY_SCOPE,
            "total": int(summary_total or 0),
            "positive_ev_count": int(positive_ev or 0),
            "avg_confidence": float(confidence) if confidence is not None else None,
            "model_count": int(model_count or 0),
            "latest_predict_time": (
                latest_time.isoformat()
                if latest_time is not None and hasattr(latest_time, "isoformat")
                else str(latest_time)
                if latest_time is not None
                else None
            ),
            "data_as_of": data_as_of,
            "computed_at": computed_at,
        },
    }


_REFRESH_PREDICTION_STATISTICS_SQL = f"""
    WITH RECURSIVE
    {canonical_prediction_rows_ctes(match_scope="prediction_statistics_refresh_targets", legacy_strategy="scoped_scan")},
    eligible_canonical_rows AS MATERIALIZED (
        SELECT p.match_id, mv.model_name, p.ev, p.confidence_score, p.predict_time
        FROM canonical_prediction_rows p
        JOIN model_versions mv ON mv.id = p.model_version_id
        JOIN official_matches m ON m.id = p.match_id
        WHERE p.validation_status = 'valid'
          AND p.predict_time < m.kickoff_time
    ),
    canonical_rollups AS (
        SELECT
            match_id,
            COUNT(*)::BIGINT AS summary_total,
            COUNT(*) FILTER (WHERE ev > 0)::BIGINT AS summary_positive_ev_count,
            COALESCE(SUM(confidence_score), 0::NUMERIC) AS confidence_sum,
            COUNT(confidence_score)::BIGINT AS confidence_count,
            ARRAY_AGG(DISTINCT model_name::TEXT ORDER BY model_name::TEXT) AS model_names,
            MAX(predict_time) AS latest_predict_time
        FROM eligible_canonical_rows
        GROUP BY match_id
    ),
    raw_rollups AS (
        SELECT
            targets.match_id,
            raw.total AS raw_prediction_total
        FROM prediction_statistics_refresh_targets targets
        JOIN official_matches m ON m.id = targets.match_id
        CROSS JOIN LATERAL (
            SELECT COUNT(*)::BIGINT AS total
            FROM model_predictions p
            JOIN model_versions mv ON mv.id = p.model_version_id
            WHERE p.match_id = targets.match_id
              AND p.validation_status = 'valid'
              AND p.predict_time < m.kickoff_time
        ) raw
    )
    INSERT INTO prediction_statistics_match_rollups (
        match_id, raw_prediction_total, summary_total, summary_positive_ev_count,
        confidence_sum, confidence_count, model_names, latest_predict_time, refreshed_at
    )
    SELECT
        targets.match_id,
        COALESCE(raw.raw_prediction_total, 0),
        COALESCE(canonical.summary_total, 0),
        COALESCE(canonical.summary_positive_ev_count, 0),
        COALESCE(canonical.confidence_sum, 0::NUMERIC),
        COALESCE(canonical.confidence_count, 0),
        COALESCE(canonical.model_names, ARRAY[]::TEXT[]),
        canonical.latest_predict_time,
        clock_timestamp()
    FROM prediction_statistics_refresh_targets targets
    JOIN official_matches m ON m.id = targets.match_id
    LEFT JOIN raw_rollups raw ON raw.match_id = targets.match_id
    LEFT JOIN canonical_rollups canonical ON canonical.match_id = targets.match_id
    ON CONFLICT (match_id) DO UPDATE SET
        raw_prediction_total = EXCLUDED.raw_prediction_total,
        summary_total = EXCLUDED.summary_total,
        summary_positive_ev_count = EXCLUDED.summary_positive_ev_count,
        confidence_sum = EXCLUDED.confidence_sum,
        confidence_count = EXCLUDED.confidence_count,
        model_names = EXCLUDED.model_names,
        latest_predict_time = EXCLUDED.latest_predict_time,
        refreshed_at = EXCLUDED.refreshed_at
"""

_PREDICTION_STATISTICS_SNAPSHOT_SQL = """
    WITH pending AS MATERIALIZED (
        SELECT COUNT(*)::BIGINT AS pending_matches
        FROM prediction_statistics_dirty_matches
    ), rollups AS MATERIALIZED (
        SELECT
            COALESCE(SUM(raw_prediction_total), 0)::BIGINT AS raw_total,
            COALESCE(SUM(summary_total), 0)::BIGINT AS summary_total,
            COALESCE(SUM(summary_positive_ev_count), 0)::BIGINT AS positive_ev_count,
            SUM(confidence_sum) AS confidence_sum,
            COALESCE(SUM(confidence_count), 0)::BIGINT AS confidence_count,
            MAX(latest_predict_time) AS latest_predict_time
        FROM prediction_statistics_match_rollups
    ), model_count AS MATERIALIZED (
        SELECT COUNT(DISTINCT names.model_name)::INT AS total
        FROM prediction_statistics_match_rollups rollup
        CROSS JOIN LATERAL UNNEST(rollup.model_names) AS names(model_name)
    )
    SELECT pending.pending_matches,
           rollups.raw_total,
           rollups.summary_total,
           rollups.positive_ev_count,
           CASE WHEN rollups.confidence_count > 0
                THEN rollups.confidence_sum / rollups.confidence_count
                ELSE NULL END AS avg_confidence,
           model_count.total,
           rollups.latest_predict_time,
           statement_timestamp(),
           clock_timestamp()
    FROM pending CROSS JOIN rollups CROSS JOIN model_count
"""


def _set_local_statement_timeout(cur: Any, timeout_seconds: int) -> None:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("statement timeout must be between 1 and 120 seconds")
    cur.execute(f"SET LOCAL statement_timeout = '{timeout_seconds}s'")


def _execute_with_local_timeout(
    cur: Any, statement: str, timeout_seconds: int, params: Any = None
) -> None:
    """Apply a transaction-local timeout immediately before executing SQL."""
    _set_local_statement_timeout(cur, timeout_seconds)
    if params is None:
        cur.execute(statement)
    else:
        cur.execute(statement, params)


def _refresh_prediction_statistics_batch(
    conn: Any, *, batch_size: int = DEFAULT_REFRESH_BATCH_SIZE
) -> dict[str, Any]:
    """Refresh at most one bounded dirty-match batch; caller owns the job lock."""
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_REFRESH_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_REFRESH_BATCH_SIZE}")

    with conn.cursor() as cur:
        _execute_with_local_timeout(
            cur,
            """
            CREATE TEMP TABLE prediction_statistics_refresh_targets ON COMMIT DROP AS
            WITH claimed AS MATERIALIZED (
                SELECT match_id
                FROM prediction_statistics_dirty_matches
                ORDER BY changed_at, match_id
                LIMIT %(batch_size)s
                FOR UPDATE SKIP LOCKED
            ), deleted AS (
                DELETE FROM prediction_statistics_dirty_matches dirty
                USING claimed
                WHERE dirty.match_id = claimed.match_id
                RETURNING dirty.match_id
            )
            SELECT match_id FROM deleted
            """,
            CLAIM_STATEMENT_TIMEOUT_SECONDS,
            {"batch_size": batch_size},
        )
        matches_refreshed = max(cur.rowcount, 0)
        _execute_with_local_timeout(
            cur,
            "ANALYZE prediction_statistics_refresh_targets",
            CLAIM_STATEMENT_TIMEOUT_SECONDS,
        )
        _execute_with_local_timeout(
            cur,
            """DELETE FROM prediction_statistics_match_rollups rollup
               USING prediction_statistics_refresh_targets target
               WHERE rollup.match_id = target.match_id
                 AND NOT EXISTS (
                     SELECT 1 FROM official_matches match
                     WHERE match.id = target.match_id
                 )""",
            ORPHAN_DELETE_STATEMENT_TIMEOUT_SECONDS,
        )
        _execute_with_local_timeout(
            cur, _REFRESH_PREDICTION_STATISTICS_SQL, ROLLUP_STATEMENT_TIMEOUT_SECONDS
        )
        _execute_with_local_timeout(
            cur, _PREDICTION_STATISTICS_SNAPSHOT_SQL, SNAPSHOT_STATEMENT_TIMEOUT_SECONDS
        )
        row = cur.fetchone()

    if row is None:
        raise RuntimeError("prediction statistics rollup query returned no row")
    pending_matches = int(row[0])
    if pending_matches:
        return {
            "status": "partial",
            "matches_refreshed": matches_refreshed,
            "pending_matches": pending_matches,
        }

    data_as_of = row[7].astimezone(UTC).isoformat()
    computed_at = row[8].astimezone(UTC).isoformat()
    latest_predict_time = row[6]
    latest_time = (
        latest_predict_time.isoformat()
        if latest_predict_time is not None and hasattr(latest_predict_time, "isoformat")
        else str(latest_predict_time)
        if latest_predict_time is not None
        else None
    )
    return {
        "status": "completed",
        "matches_refreshed": matches_refreshed,
        "snapshots": {
            "prediction_count": {
                "scope": COUNT_SCOPE,
                "total": int(row[1]),
                "data_as_of": data_as_of,
                "computed_at": computed_at,
            },
            "prediction_summary": {
                "scope": PREDICTION_SUMMARY_SCOPE,
                "total": int(row[2]),
                "positive_ev_count": int(row[3]),
                "avg_confidence": float(row[4]) if row[4] is not None else None,
                "model_count": int(row[5]),
                "latest_predict_time": latest_time,
                "data_as_of": data_as_of,
                "computed_at": computed_at,
            },
        },
    }


def _refresh_batch_fits_run_budget(started_at: float, now: float) -> bool:
    """Reserve room for one batch before admitting it to the SQL work window.

    This is a soft admission budget, not a wall-clock kill deadline: SET commands,
    driver latency, and transaction commits can extend observed elapsed time.
    """
    elapsed = now - started_at
    return (
        elapsed >= 0
        and elapsed + REFRESH_BATCH_SQL_RESERVATION_SECONDS <= REFRESH_RUN_SQL_BUDGET_SECONDS
    )


def refresh_prediction_count(
    *,
    batch_size: int = DEFAULT_REFRESH_BATCH_SIZE,
    max_batches: int = MAX_REFRESH_BATCHES_PER_RUN,
) -> dict[str, Any]:
    """Process bounded match batches; publish only when every dirty match is current."""
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_SCHEDULED_REFRESH_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_SCHEDULED_REFRESH_BATCH_SIZE}")
    if type(max_batches) is not int or not 1 <= max_batches <= MAX_REFRESH_BATCHES_PER_RUN:
        raise ValueError(f"max_batches must be between 1 and {MAX_REFRESH_BATCHES_PER_RUN}")
    with get_db() as count_conn:
        lock_acquired = False
        try:
            with count_conn.cursor() as cur:
                _set_local_statement_timeout(cur, CLAIM_STATEMENT_TIMEOUT_SECONDS)
                cur.execute(
                    """SELECT pg_try_advisory_lock(%s, %s),
                              to_regclass('prediction_statistics_match_rollups') IS NOT NULL,
                              to_regclass('local_schema_migrations') IS NOT NULL""",
                    (913201, 114),
                )
                lock_state = cur.fetchone()
                if not lock_state[0]:
                    return {"status": "skipped", "reason": "refresh_already_running"}
                lock_acquired = True
                rollup_schema_ready = len(lock_state) > 1 and bool(lock_state[1])
                migration_ledger_ready = len(lock_state) > 2 and bool(lock_state[2])
                if not rollup_schema_ready and migration_ledger_ready:
                    return {"status": "skipped", "reason": "migration_not_applied"}
            # A session lock survives the rollup commit and remains held until
            # the separately committed audit row reaches its terminal state.
            with get_db() as audit_conn:
                run_id = start_job_run(
                    audit_conn,
                    {
                        "job_code": JOB_CODE,
                        "job_name": "有效赛前历史预测累计统计",
                        "owner_agent": "backend_agent",
                        "schedule_type": "cron",
                    },
                )
                if run_id is None:
                    raise RuntimeError("prediction count audit record was not created")
                try:
                    if rollup_schema_ready:
                        started_at = time.monotonic()
                        matches_refreshed = 0
                        pending_matches: int | None = None
                        snapshots: dict[str, Any] | None = None
                        for _batch_number in range(max_batches):
                            # The batch has four independently timed SQL
                            # statements; reserve their full budget before starting.
                            if not _refresh_batch_fits_run_budget(started_at, time.monotonic()):
                                break
                            refresh_result = _refresh_prediction_statistics_batch(
                                count_conn, batch_size=batch_size
                            )
                            count_conn.commit()
                            matches_refreshed += refresh_result["matches_refreshed"]
                            if refresh_result["status"] == "completed":
                                snapshots = refresh_result["snapshots"]
                                pending_matches = 0
                                break
                            pending_matches = refresh_result["pending_matches"]

                        if snapshots is None:
                            partial_refs = {
                                "refreshing": True,
                                "matches_refreshed": matches_refreshed,
                                "pending_matches": pending_matches,
                            }
                            finish_job_run(audit_conn, run_id, "partial", output_refs=partial_refs)
                            return {"status": "refreshing", **partial_refs}
                    else:
                        # Older isolated fixtures have no migration ledger. Keep
                        # their legacy contract; managed databases skip until 131.
                        snapshots = compute_prediction_snapshots(count_conn)
                        count_conn.commit()
                    finish_job_run(audit_conn, run_id, "completed", output_refs=snapshots)
                    return {"status": "ok", **snapshots["prediction_count"]}
                except Exception as exc:
                    audit_conn.rollback()
                    progress_refs = None
                    if rollup_schema_ready and matches_refreshed:
                        progress_refs = {
                            "refreshing": True,
                            "matches_refreshed": matches_refreshed,
                            "pending_matches": pending_matches,
                        }
                    finish_job_run(
                        audit_conn,
                        run_id,
                        "failed",
                        output_refs=progress_refs,
                        error=type(exc).__name__,
                    )
                    raise
        finally:
            count_conn.rollback()
            if lock_acquired:
                with count_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s, %s)", (913201, 114))
                    cur.fetchone()


def get_prediction_count_snapshot(conn: Any) -> dict[str, Any]:
    """Read the last successful snapshot and report its age and refresh failures."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT completed.output_refs, attempt.status, statement_timestamp()
               FROM (SELECT 1) singleton
               LEFT JOIN LATERAL (
                   SELECT output_refs FROM ai_job_runs
                   WHERE job_code = %(job_code)s AND status = 'completed'
                   ORDER BY created_at DESC, id DESC LIMIT 1
               ) completed ON true
               LEFT JOIN LATERAL (
                   SELECT status FROM ai_job_runs WHERE job_code = %(job_code)s
                   ORDER BY created_at DESC, id DESC LIMIT 1
               ) attempt ON true""",
            {"job_code": JOB_CODE},
        )
        output, attempt_status, now = cur.fetchone()
    empty = {"total": None, "status": "pending", "data_as_of": None, "last_success_at": None}
    if output is None:
        if attempt_status in {"failed", "completed"}:
            empty["status"] = "unavailable"
        return empty
    snapshot = output.get("prediction_count") if isinstance(output, dict) else None
    try:
        if not isinstance(snapshot, dict) or snapshot.get("scope") != COUNT_SCOPE:
            raise ValueError("unsupported count snapshot")
        total = snapshot["total"]
        if type(total) is not int or total < 0:
            raise ValueError("invalid count")
        data_as_of = datetime.fromisoformat(snapshot["data_as_of"])
        computed_at = datetime.fromisoformat(snapshot["computed_at"])
        if data_as_of.tzinfo is None or computed_at.tzinfo is None:
            raise ValueError("count snapshot requires a timezone")
        data_as_of, computed_at = data_as_of.astimezone(UTC), computed_at.astimezone(UTC)
        if data_as_of > computed_at or computed_at > now:
            raise ValueError("invalid count snapshot times")
    except KeyError, TypeError, ValueError, AttributeError:
        return {**empty, "status": "unavailable"}
    status = "stale" if now - data_as_of > MAX_AGE else "ok"
    if attempt_status == "failed":
        status = "refresh_failed"
    elif attempt_status == "partial":
        status = "stale"
    return {
        "total": total,
        "status": status,
        "data_as_of": data_as_of.isoformat(),
        "last_success_at": computed_at.isoformat(),
    }


def get_prediction_summary_snapshot(conn: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the last successful canonical summary with explicit freshness state."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT completed.output_refs, attempt.status, statement_timestamp(), attempt.created_at
               FROM (SELECT 1) singleton
               LEFT JOIN LATERAL (
                   SELECT output_refs FROM ai_job_runs
                   WHERE job_code = %(job_code)s AND status = 'completed'
                   ORDER BY created_at DESC, id DESC LIMIT 1
               ) completed ON true
               LEFT JOIN LATERAL (
                   SELECT status, created_at FROM ai_job_runs WHERE job_code = %(job_code)s
                   ORDER BY created_at DESC, id DESC LIMIT 1
               ) attempt ON true""",
            {"job_code": JOB_CODE},
        )
        output, attempt_status, database_now, attempt_at = cur.fetchone()
    current_time = now or database_now
    if current_time.tzinfo is None:
        raise ValueError("summary snapshot clock must be timezone-aware")
    current_time = current_time.astimezone(UTC)
    refresh_in_progress = attempt_status in {"running", "partial"}
    last_attempt_at = (
        attempt_at.astimezone(UTC).isoformat()
        if attempt_at is not None and attempt_at.tzinfo is not None
        else None
    )
    empty_meta = {
        "status": "pending",
        "data_as_of": None,
        "last_success_at": None,
        "last_attempt_at": last_attempt_at,
        "age_seconds": None,
        "stale_after_seconds": int(MAX_AGE.total_seconds()),
        "is_stale": False,
    }
    if output is None:
        if refresh_in_progress:
            empty_meta["status"] = "refreshing"
            empty_meta["is_stale"] = True
        elif attempt_status in {"failed", "completed"}:
            empty_meta["status"] = "unavailable"
        return {"summary": None, "meta": empty_meta}

    snapshot = output.get("prediction_summary") if isinstance(output, dict) else None
    try:
        if not isinstance(snapshot, dict) or snapshot.get("scope") != PREDICTION_SUMMARY_SCOPE:
            raise ValueError("unsupported prediction summary snapshot")
        total = snapshot["total"]
        positive_ev_count = snapshot["positive_ev_count"]
        model_count = snapshot["model_count"]
        confidence = snapshot["avg_confidence"]
        latest_predict_time = snapshot["latest_predict_time"]
        if type(total) is not int or total < 0:
            raise ValueError("invalid total")
        if type(positive_ev_count) is not int or not 0 <= positive_ev_count <= total:
            raise ValueError("invalid positive EV count")
        if type(model_count) is not int or not 0 <= model_count <= total:
            raise ValueError("invalid model count")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("invalid average confidence")
        if latest_predict_time is not None and not isinstance(latest_predict_time, str):
            raise ValueError("invalid latest prediction time")
        data_as_of = datetime.fromisoformat(snapshot["data_as_of"])
        computed_at = datetime.fromisoformat(snapshot["computed_at"])
        if data_as_of.tzinfo is None or computed_at.tzinfo is None:
            raise ValueError("summary timestamps require a timezone")
        data_as_of, computed_at = data_as_of.astimezone(UTC), computed_at.astimezone(UTC)
        if data_as_of > computed_at or computed_at > current_time:
            raise ValueError("invalid summary timestamps")
    except KeyError, TypeError, ValueError, AttributeError:
        return {
            "summary": None,
            "meta": {
                **empty_meta,
                "status": "refreshing" if refresh_in_progress else "unavailable",
                "is_stale": refresh_in_progress,
            },
        }

    age_seconds = max(0, int((current_time - data_as_of).total_seconds()))
    is_stale = age_seconds > MAX_AGE.total_seconds()
    status = (
        "refresh_failed"
        if attempt_status == "failed"
        else "stale"
        if refresh_in_progress
        else "stale"
        if is_stale
        else "ok"
    )
    return {
        "summary": {
            "total": total,
            "positive_ev_count": positive_ev_count,
            "avg_confidence": float(confidence) if confidence is not None else None,
            "model_count": model_count,
            "latest_predict_time": latest_predict_time,
        },
        "meta": {
            "status": status,
            "data_as_of": data_as_of.isoformat(),
            "last_success_at": computed_at.isoformat(),
            "last_attempt_at": last_attempt_at,
            "age_seconds": age_seconds,
            "stale_after_seconds": int(MAX_AGE.total_seconds()),
            "is_stale": is_stale or refresh_in_progress,
        },
    }
