"""Prediction read scopes and exact scheduled historical count snapshots."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agent_storage import finish_job_run, start_job_run

JOB_CODE = "refresh_prediction_count"
COUNT_SCOPE = "valid_prematch_history_v1"
MAX_AGE = timedelta(minutes=45)


def latest_prediction_ctes(
    *,
    filter_match: bool,
    filter_match_ids: bool = False,
    match_scope: str | None = None,
    spf_only: bool = False,
) -> str:
    """Seek legacy match/version/play keys before enumerating uncovered options."""
    group_match = "AND g.match_id = %(match_id)s" if filter_match else ""
    key_match = "WHERE p.match_id = %(match_id)s" if filter_match else ""
    next_match = "AND p.match_id = %(match_id)s" if filter_match else ""
    play_filter = "AND p.play_type = 'spf'" if spf_only else ""
    if filter_match_ids:
        group_match = "AND g.match_id = ANY(%(match_ids)s::bigint[])"
        key_match = "WHERE p.match_id = ANY(%(match_ids)s::bigint[])"
        next_match = "AND p.match_id = ANY(%(match_ids)s::bigint[])"
    key_filters = play_filter
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
                            ORDER BY p.model_version_id, p.play_type LIMIT 1
                        )
                        UNION ALL
                        SELECT next_key.* FROM match_keys previous
                        CROSS JOIN LATERAL (
                            SELECT p.model_version_id, p.play_type FROM model_predictions p
                            WHERE p.match_id = scoped.match_id
                              {play_filter}
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
                WITH RECURSIVE option_keys AS (
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
    prefix: str = "",
) -> str:
    """Canonical IDs before validity/time filters; preserve complete-group shielding."""
    result = f"""
        {latest_prediction_ctes(filter_match=False, match_scope=match_scope, spf_only=spf_only)},
        canonical_prediction_ids AS (
            SELECT mapped.prediction_id AS id FROM latest_groups groups
            JOIN model_prediction_group_options mapped ON mapped.group_id = groups.group_id
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


def refresh_prediction_count() -> dict[str, Any]:
    """Persist a complete snapshot; a failed count leaves prior success intact."""
    with get_db() as count_conn:
        try:
            with count_conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '120s'")
                cur.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (913201, 114))
                if not cur.fetchone()[0]:
                    return {"status": "skipped", "reason": "refresh_already_running"}
            # Keep the lock on the count connection while the existing audit
            # helpers commit on a separate connection. Historical audit records
            # have no ownership protocol, so do not infer their interruption.
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
                    result = compute_prediction_count(count_conn)
                    finish_job_run(
                        audit_conn, run_id, "completed", output_refs={"prediction_count": result}
                    )
                    return {"status": "ok", **result}
                except Exception as exc:
                    audit_conn.rollback()
                    finish_job_run(audit_conn, run_id, "failed", error=type(exc).__name__)
                    raise
        finally:
            # This connection only reads business data. Release its transaction
            # and advisory lock even on timeout or a failed audit write.
            count_conn.rollback()


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
    return {
        "total": total,
        "status": status,
        "data_as_of": data_as_of.isoformat(),
        "last_success_at": computed_at.isoformat(),
    }
