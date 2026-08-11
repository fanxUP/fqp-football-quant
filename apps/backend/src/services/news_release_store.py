"""Human-controlled release state for the News Intelligence overlay."""

from __future__ import annotations

from typing import Any

from scripts.news_feature_snapshots import FEATURE_VERSION
from scripts.news_release_policy import assess_promotion
from scripts.news_shadow_model import SHADOW_VERSION


def _metrics(conn: Any, shadow_version: str = SHADOW_VERSION) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(evaluation.id),
                   AVG(evaluation.shadow_brier - evaluation.baseline_brier),
                   AVG(evaluation.shadow_log_loss - evaluation.baseline_log_loss)
            FROM news_shadow_predictions shadow
            JOIN news_shadow_evaluations evaluation
                ON evaluation.shadow_prediction_id = shadow.id
            WHERE shadow.shadow_version = %s
            """,
            (shadow_version,),
        )
        row = cur.fetchone() or (0, None, None)
    return {
        "sampleSize": int(row[0] or 0),
        "brierDelta": float(row[1]) if row[1] is not None else None,
        "logLossDelta": float(row[2]) if row[2] is not None else None,
    }


def get_news_release(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mode, approved_shadow_version, approved_feature_version,
                   approval_note, approved_by, approved_at, updated_at
            FROM news_feature_release_settings WHERE id = 1
            """
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("新闻发布配置不存在")
    metrics = _metrics(conn)
    assessment = assess_promotion(
        sample_size=metrics["sampleSize"],
        brier_delta=metrics["brierDelta"],
        log_loss_delta=metrics["logLossDelta"],
    )
    return {
        "mode": row[0],
        "approvedShadowVersion": row[1],
        "approvedFeatureVersion": row[2],
        "approvalNote": row[3],
        "approvedBy": row[4],
        "approvedAt": row[5].isoformat() if row[5] else None,
        "updatedAt": row[6].isoformat() if row[6] else None,
        "candidateShadowVersion": SHADOW_VERSION,
        "candidateFeatureVersion": FEATURE_VERSION,
        "metrics": metrics,
        "promotion": assessment,
    }


def promote_news_release(conn: Any, *, approval_note: str) -> dict[str, Any]:
    metrics = _metrics(conn)
    assessment = assess_promotion(
        sample_size=metrics["sampleSize"],
        brier_delta=metrics["brierDelta"],
        log_loss_delta=metrics["logLossDelta"],
    )
    if not assessment["eligible"]:
        raise ValueError(str(assessment["reason"]))
    with conn.cursor() as cur:
        cur.execute("SELECT mode FROM news_feature_release_settings WHERE id = 1 FOR UPDATE")
        row = cur.fetchone()
        if not row:
            raise ValueError("新闻发布配置不存在")
        previous_mode = str(row[0])
        cur.execute(
            """
            UPDATE news_feature_release_settings
            SET mode = 'production', approved_shadow_version = %s,
                approved_feature_version = %s, approval_note = %s,
                approved_by = 'admin', approved_at = NOW(), updated_at = NOW()
            WHERE id = 1
            """,
            (SHADOW_VERSION, FEATURE_VERSION, approval_note),
        )
        cur.execute(
            """
            INSERT INTO news_feature_release_history (
                action, previous_mode, new_mode, shadow_version, feature_version,
                sample_size, brier_delta, log_loss_delta, action_note
            )
            VALUES ('promote', %s, 'production', %s, %s, %s, %s, %s, %s)
            """,
            (
                previous_mode,
                SHADOW_VERSION,
                FEATURE_VERSION,
                metrics["sampleSize"],
                metrics["brierDelta"],
                metrics["logLossDelta"],
                approval_note,
            ),
        )
    conn.commit()
    return get_news_release(conn)


def rollback_news_release(conn: Any, *, rollback_note: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT mode FROM news_feature_release_settings WHERE id = 1 FOR UPDATE")
        row = cur.fetchone()
        if not row:
            raise ValueError("新闻发布配置不存在")
        previous_mode = str(row[0])
        cur.execute(
            """
            UPDATE news_feature_release_settings
            SET mode = 'shadow', approved_shadow_version = NULL,
                approved_feature_version = NULL, approval_note = %s,
                approved_by = 'admin', approved_at = NULL, updated_at = NOW()
            WHERE id = 1
            """,
            (rollback_note,),
        )
        cur.execute(
            """
            INSERT INTO news_feature_release_history (
                action, previous_mode, new_mode, shadow_version, feature_version,
                action_note
            )
            VALUES ('rollback', %s, 'shadow', %s, %s, %s)
            """,
            (previous_mode, SHADOW_VERSION, FEATURE_VERSION, rollback_note),
        )
    conn.commit()
    return get_news_release(conn)
