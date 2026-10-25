"""Prediction read scopes and exact scheduled historical count snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agent_storage import finish_job_run, recover_interrupted_job_runs, start_job_run

JOB_CODE = "refresh_prediction_count"
COUNT_SCOPE = "valid_prematch_history_v1"
MAX_AGE = timedelta(minutes=45)


def latest_prediction_ctes(*, filter_match: bool) -> str:
    """CTEs matching migration 111, with index seeks over legacy identities.

    Prefix with WITH RECURSIVE. Keys are non-null in the prediction schema;
    migration 113 supplies their ordered index. Taking the newest unmapped row
    per version before comparing same-name versions is equivalent to ranking
    all unmapped rows. Validity and kickoff filters must remain outside.
    """
    group_match = "AND g.match_id = %(match_id)s" if filter_match else ""
    key_match = "WHERE p.match_id = %(match_id)s" if filter_match else ""
    next_match = "AND p.match_id = %(match_id)s" if filter_match else ""
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
            ORDER BY g.match_id, mv.model_name, g.play_type,
                     g.predict_time DESC, g.created_at DESC, g.id DESC
        ), legacy_keys AS (
            (
                SELECT p.match_id, p.model_version_id, p.play_type, p.option_code
                FROM model_predictions p {key_match}
                ORDER BY p.match_id, p.model_version_id, p.play_type, p.option_code
                LIMIT 1
            )
            UNION ALL
            SELECT next_key.* FROM legacy_keys previous
            CROSS JOIN LATERAL (
                SELECT p.match_id, p.model_version_id, p.play_type, p.option_code
                FROM model_predictions p
                WHERE (p.match_id, p.model_version_id, p.play_type, p.option_code)
                    > (previous.match_id, previous.model_version_id,
                       previous.play_type, previous.option_code)
                  {next_match}
                ORDER BY p.match_id, p.model_version_id, p.play_type, p.option_code
                LIMIT 1
            ) next_key
        ), eligible_legacy_keys AS MATERIALIZED (
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
                SELECT p.* FROM model_predictions p
                WHERE p.match_id = keys.match_id
                  AND p.model_version_id = keys.model_version_id
                  AND p.play_type = keys.play_type AND p.option_code = keys.option_code
                  AND NOT EXISTS (
                      SELECT 1 FROM model_prediction_group_options mapped
                      WHERE mapped.prediction_id = p.id
                  )
                ORDER BY p.predict_time DESC, p.id DESC LIMIT 1
            ) p
        ), legacy_latest AS (
            SELECT DISTINCT ON (match_id, model_name, play_type, option_code) *
            FROM legacy_by_version
            ORDER BY match_id, model_name, play_type, option_code, predict_time DESC, id DESC
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
            # helpers commit on a separate connection. Only its lock owner may
            # recover an interrupted execution of this job.
            with get_db() as audit_conn:
                recover_interrupted_job_runs(audit_conn, [JOB_CODE])
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
