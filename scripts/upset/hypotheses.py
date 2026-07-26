"""Research-only hypothesis extraction, validation, and promotion audit."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg2.extras import Json, RealDictCursor

STATES = (
    "research_only",
    "backtesting",
    "out_of_sample",
    "simulation",
    "feature_candidate",
    "promoted",
    "rejected",
    "retired",
)
TRANSITIONS = {
    "research_only": {"backtesting", "rejected", "retired"},
    "backtesting": {"out_of_sample", "rejected", "retired"},
    "out_of_sample": {"simulation", "rejected", "retired"},
    "simulation": {"feature_candidate", "rejected", "retired"},
    "feature_candidate": {"promoted", "rejected", "retired"},
    "promoted": {"retired"},
    "rejected": {"retired"},
    "retired": set(),
}
REQUIRED_VALIDATIONS = {"backtest", "out_of_sample", "simulation"}


def can_transition(current: str, target: str) -> bool:
    if current not in STATES or target not in STATES:
        raise ValueError("未知研究状态")
    return target in TRANSITIONS[current]


def promotion_requirements_met(validation_results: dict[str, bool]) -> bool:
    return all(validation_results.get(kind) is True for kind in REQUIRED_VALIDATIONS)


def evaluate_validation_metrics(
    metrics: dict[str, Any], thresholds: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Evaluate one backtest/OOS/simulation result using explicit thresholds."""
    reasons = []
    if int(metrics.get("n_bets") or 0) < int(thresholds.get("min_bets") or 0):
        reasons.append("INSUFFICIENT_SAMPLE")
    if float(metrics.get("roi") or 0) < float(thresholds.get("min_roi") or 0):
        reasons.append("ROI_BELOW_THRESHOLD")
    if metrics.get("brier_score") is None or float(metrics["brier_score"]) > float(
        thresholds.get("max_brier", 1)
    ):
        reasons.append("BRIER_TOO_HIGH")
    if metrics.get("max_drawdown_pct") is None or float(metrics["max_drawdown_pct"]) > float(
        thresholds.get("max_drawdown_pct", 1)
    ):
        reasons.append("DRAWDOWN_TOO_HIGH")
    return not reasons, reasons


def _hypothesis_key(event_id: int, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return f"upset-{event_id}-{digest}"


def extract_review_hypotheses(conn: Any) -> dict[str, int]:
    """Persist only structured review hypotheses; never invent one from prose."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT review.upset_event_id, review.hypotheses_json
            FROM upset_reviews review
            WHERE review.validation_status = 'validated'
              AND jsonb_array_length(review.hypotheses_json) > 0
            ORDER BY review.id
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
    inserted = 0
    skipped = 0
    for row in rows:
        for item in row["hypotheses_json"]:
            if not isinstance(item, dict) or not item.get("conditions") or not item.get("target"):
                skipped += 1
                continue
            event_id = int(row["upset_event_id"])
            key = _hypothesis_key(event_id, item)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_hypotheses (
                        hypothesis_key, hypothesis_version, source_upset_event_id,
                        title, description, conditions_json, target_json,
                        status, sample_size, confidence
                    ) VALUES (%s, 'research-v1', %s, %s, %s, %s, %s,
                              'research_only', 0, %s)
                    ON CONFLICT (hypothesis_key, hypothesis_version) DO NOTHING
                    RETURNING id
                    """,
                    (
                        key,
                        event_id,
                        item.get("title") or "冷门复盘研究假设",
                        item.get("description"),
                        Json(item["conditions"]),
                        Json(item["target"]),
                        float(item.get("confidence") or 0),
                    ),
                )
                inserted += int(cur.fetchone() is not None)
    conn.commit()
    return {"reviews": len(rows), "inserted": inserted, "skipped": skipped}


def record_validation(
    conn: Any,
    *,
    hypothesis_id: int,
    validation_type: str,
    metrics: dict[str, Any],
    passed: bool,
    failure_reasons: list[str] | None = None,
    backtest_run_id: int | None = None,
    code_version: str | None = None,
) -> int:
    if validation_type not in REQUIRED_VALIDATIONS:
        raise ValueError("未知验证类型")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hypothesis_validation_runs (
                hypothesis_id, validation_type, backtest_run_id, metrics_json,
                passed, failure_reasons_json, code_version, started_at, finished_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,now(),now()) RETURNING id
            """,
            (
                hypothesis_id,
                validation_type,
                backtest_run_id,
                Json(metrics),
                passed,
                Json(failure_reasons or []),
                code_version,
            ),
        )
        validation_id = int(cur.fetchone()[0])
    conn.commit()
    return validation_id


def record_completed_backtest_validation(
    conn: Any,
    *,
    hypothesis_id: int,
    validation_type: str,
    backtest_run_id: int,
    thresholds: dict[str, Any],
    code_version: str | None = None,
) -> int:
    """Link a completed existing backtest to one audited validation stage."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT run.status, result.n_bets, result.roi, result.brier_score,
                   result.log_loss, result.max_drawdown_pct, result.sharpe_ratio
            FROM backtest_runs run
            JOIN backtest_run_results result ON result.run_id=run.id
            WHERE run.id=%s AND result.window_index IS NULL
            ORDER BY result.id DESC LIMIT 1
            """,
            (backtest_run_id,),
        )
        row = cur.fetchone()
    if not row or row["status"] != "completed":
        raise ValueError("只能关联已完成且包含汇总指标的回测")
    metrics = {
        "n_bets": int(row["n_bets"] or 0),
        **{
            key: float(row[key]) if row[key] is not None else None
            for key in (
                "roi",
                "brier_score",
                "log_loss",
                "max_drawdown_pct",
                "sharpe_ratio",
            )
        },
    }
    passed, reasons = evaluate_validation_metrics(metrics, thresholds)
    return record_validation(
        conn,
        hypothesis_id=hypothesis_id,
        validation_type=validation_type,
        metrics={**metrics, "thresholds": thresholds},
        passed=passed,
        failure_reasons=reasons,
        backtest_run_id=backtest_run_id,
        code_version=code_version,
    )


def _latest_validation_results(conn: Any, hypothesis_id: int) -> tuple[dict[str, bool], list[int]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (validation_type) id, validation_type, passed
            FROM hypothesis_validation_runs
            WHERE hypothesis_id=%s
            ORDER BY validation_type, started_at DESC, id DESC
            """,
            (hypothesis_id,),
        )
        rows = cur.fetchall()
    return ({str(row[1]): bool(row[2]) for row in rows}, [int(row[0]) for row in rows])


def transition_hypothesis(
    conn: Any,
    *,
    hypothesis_id: int,
    target_status: str,
    decision_reason: str,
    feature_set_version: str | None = None,
    decided_by: str = "system_validation",
    rollback_reference: str | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM research_hypotheses WHERE id=%s FOR UPDATE",
            (hypothesis_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("研究假设不存在")
    current = str(row[0])
    if not can_transition(current, target_status):
        raise ValueError(f"不允许从{current}迁移到{target_status}")
    results, validation_ids = _latest_validation_results(conn, hypothesis_id)
    validation_gate = {
        "out_of_sample": {"backtest"},
        "simulation": {"backtest", "out_of_sample"},
        "feature_candidate": REQUIRED_VALIDATIONS,
        "promoted": REQUIRED_VALIDATIONS,
    }.get(target_status, set())
    if not all(results.get(kind) is True for kind in validation_gate):
        raise ValueError("缺少通过的前置验证，禁止晋级")
    if target_status == "promoted" and not feature_set_version:
        raise ValueError("正式晋级必须指定特征集版本")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE research_hypotheses SET status=%s, updated_at=now() WHERE id=%s",
            (target_status, hypothesis_id),
        )
        cur.execute(
            """
            INSERT INTO feature_promotion_audits (
                hypothesis_id, from_status, to_status, feature_set_version,
                validation_run_ids_json, decision_reason, decided_by,
                rollback_reference, decided_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) RETURNING id
            """,
            (
                hypothesis_id,
                current,
                target_status,
                feature_set_version,
                Json(validation_ids),
                decision_reason,
                decided_by,
                rollback_reference,
            ),
        )
        audit_id = int(cur.fetchone()[0])
    conn.commit()
    return {
        "hypothesis_id": hypothesis_id,
        "from_status": current,
        "to_status": target_status,
        "audit_id": audit_id,
        "validation_run_ids": validation_ids,
    }
