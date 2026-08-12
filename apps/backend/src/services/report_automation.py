"""Optional, failure-isolated model interpretation for completed reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from apps.backend.src.services.agent_workspace_store import (
    create_workspace_task,
    has_workspace_task_for_source,
)
from apps.backend.src.services.model_gateway import invoke_agent_model, model_failure_metadata
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import list_agent_model_bindings

POST_MATCH_REPORT_AGENT = "post_match_report_agent"
POST_MATCH_REPORT_AUTOMATION_KEY = "post_match_report"
_MAX_SNAPSHOT_CHARS = 6_000
_MAX_REPORT_ATTEMPTS = 3
_REPORT_RETRY_COOLDOWN = timedelta(hours=2)
_REPORT_SOURCE_TYPES = {
    "post_daily": "daily",
    "post_weekly": "weekly",
    "post_monthly": "monthly",
}


def _report_digest(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the model prompt focused on compact, already-derived report facts."""
    digest = {
        key: snapshot.get(key)
        for key in (
            "schemaVersion",
            "dailyReview",
            "aggregate",
            "researchMetrics",
            "performanceMetrics",
            "performanceBreakdowns",
            "evidenceSummary",
            "strategySummary",
            "upsetSummary",
            "dailyReportRefs",
        )
        if snapshot.get(key) is not None
    }
    errors = snapshot.get("errorAnalysis")
    if isinstance(errors, Mapping):
        digest["errorAnalysis"] = {
            "errorCount": errors.get("errorCount"),
            "byType": errors.get("byType") or [],
        }
    return digest


def is_post_match_report_automation_enabled(conn: Any) -> bool:
    """Return False until an administrator explicitly enables the automation."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT enabled FROM report_automation_settings WHERE setting_key = %s",
            (POST_MATCH_REPORT_AUTOMATION_KEY,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def get_post_match_report_automation(conn: Any) -> dict[str, Any]:
    """Expose only safe automation status and the selected Agent readiness."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT enabled FROM report_automation_settings WHERE setting_key = %s",
            (POST_MATCH_REPORT_AUTOMATION_KEY,),
        )
        row = cur.fetchone()
    binding = next(
        (
            item
            for item in list_agent_model_bindings(conn)
            if item["agentCode"] == POST_MATCH_REPORT_AGENT
        ),
        None,
    )
    return {
        "enabled": bool(row and row[0]),
        "agentCode": POST_MATCH_REPORT_AGENT,
        "agentReady": bool(
            binding
            and binding["enabled"]
            and binding["providerEnabled"]
            and binding["providerTestStatus"] == "passed"
        ),
        "providerName": binding["providerName"] if binding else None,
        "model": binding["model"] if binding else None,
    }


def set_post_match_report_automation(conn: Any, enabled: bool) -> dict[str, Any]:
    """Persist explicit opt-in only when the dedicated Agent is ready."""
    current = get_post_match_report_automation(conn)
    if enabled and not current["agentReady"]:
        raise ValueError("请先启用并测试自动赛后报告 Agent")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO report_automation_settings (setting_key, enabled, updated_at)
               VALUES (%s, %s, now())
               ON CONFLICT (setting_key) DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()""",
            (POST_MATCH_REPORT_AUTOMATION_KEY, enabled),
        )
    conn.commit()
    return {**current, "enabled": enabled}


def _build_prompt(source_type: str, source_ref: str, snapshot: Mapping[str, Any]) -> str:
    material = json.dumps(_report_digest(snapshot), ensure_ascii=False, default=str, sort_keys=True)
    truncated = len(material) > _MAX_SNAPSHOT_CHARS
    material = material[:_MAX_SNAPSHOT_CHARS]
    return (
        "请基于以下后端冻结的赛后报告材料，生成简洁的中文量化研究复盘。\n"
        "严格使用以下 Markdown 二级标题，标题不可省略；无数据时写“当前材料不足，无法判断”。\n"
        "## 一、已确认事实\n"
        "仅列出官方赛果、已结算数据和快照内的覆盖率，不做推断。\n"
        "## 二、模型与市场\n"
        "说明模型概率、市场概率、Edge、EV 与冷门信号；"
        "必须解读 Brier Score、Log Loss、概率校准、CLV，且将信号和事实分开。\n"
        "## 三、结果与盈亏\n"
        "说明模拟与实盘的投入、返还、盈亏、ROI、回撤或样本不足；不得提供投注指令。\n"
        "## 四、异常与证据缺口\n"
        "列出赛果、赔率、模型、错因或新闻证据的缺失与异常；没有时明确写无。\n"
        "## 五、待人工核验\n"
        "列出需人工比对的项目；不得新增外部事实、不得修改模型或业务记录。\n"
        "模型输出仅供人工核验。\n"
        f"来源：{source_type}/{source_ref}。"
        + ("材料因长度限制已截断。\n" if truncated else "\n")
        + "冻结材料：\n"
        + material
    )


def _record_safely(conn: Any, **kwargs: Any) -> None:
    """An audit write failure must not make a completed business report fail."""
    try:
        record_model_invocation(conn, **kwargs)
    except Exception:
        return None


def _report_attempt_gate(
    conn: Any,
    *,
    source_type: str,
    source_ref: str,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    report_type = _REPORT_SOURCE_TYPES.get(source_type)
    if report_type is None:
        return True, None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT model_report_status, model_report_attempt_count,
                      model_report_last_attempt_at
               FROM report_generation_runs
               WHERE report_type = %s AND period_key = %s AND status = 'completed'""",
            (report_type, source_ref),
        )
        row = cur.fetchone()
    if not row:
        return False, "report_snapshot_missing"
    status, attempts, last_attempt_at = row
    if status == "completed":
        return False, "already_archived"
    if int(attempts or 0) >= _MAX_REPORT_ATTEMPTS:
        return False, "retry_exhausted"
    current = now or datetime.now(UTC)
    if last_attempt_at:
        normalized = (
            last_attempt_at.replace(tzinfo=UTC)
            if last_attempt_at.tzinfo is None
            else last_attempt_at.astimezone(UTC)
        )
        if normalized > current - _REPORT_RETRY_COOLDOWN:
            return False, "retry_cooldown"
    return True, None


def _record_report_attempt(
    conn: Any,
    *,
    source_type: str,
    source_ref: str,
    status: str,
    error_code: str | None,
) -> None:
    report_type = _REPORT_SOURCE_TYPES.get(source_type)
    if report_type is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE report_generation_runs
               SET model_report_status = %s,
                   model_report_attempt_count = model_report_attempt_count + 1,
                   model_report_last_attempt_at = NOW(),
                   model_report_error_code = %s
               WHERE report_type = %s AND period_key = %s AND status = 'completed'""",
            (status, error_code, report_type, source_ref),
        )
    conn.commit()


def retry_completed_report_interpretation(
    conn: Any,
    *,
    source_type: str,
    source_ref: str,
    title: str,
) -> dict[str, Any]:
    """Retry only a missing optional interpretation; never rebuild report facts."""
    report_type = _REPORT_SOURCE_TYPES[source_type]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT source_snapshot_json
               FROM report_generation_runs
               WHERE report_type = %s AND period_key = %s AND status = 'completed'""",
            (report_type, source_ref),
        )
        row = cur.fetchone()
    if not row or not isinstance(row[0], Mapping):
        return {"status": "skipped", "reason": "report_snapshot_missing"}
    return maybe_generate_post_match_report(
        conn,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        snapshot=row[0],
    )


def maybe_generate_post_match_report(
    conn: Any,
    *,
    source_type: str,
    source_ref: str,
    title: str,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Archive one optional report interpretation without affecting report facts."""
    if not is_post_match_report_automation_enabled(conn):
        return {"status": "skipped", "reason": "automation_disabled"}
    if has_workspace_task_for_source(
        conn,
        agent_code=POST_MATCH_REPORT_AGENT,
        source_type=source_type,
        source_ref=source_ref,
    ):
        return {"status": "skipped", "reason": "already_archived"}
    allowed, reason = _report_attempt_gate(
        conn,
        source_type=source_type,
        source_ref=source_ref,
    )
    if not allowed:
        return {"status": "skipped", "reason": reason}

    prompt = _build_prompt(source_type, source_ref, snapshot)
    started_at = perf_counter()
    try:
        result = invoke_agent_model(conn, POST_MATCH_REPORT_AGENT, prompt)
        task = create_workspace_task(
            conn,
            title=title,
            agent_code=POST_MATCH_REPORT_AGENT,
            provider_code=result.provider_code,
            model=result.model,
            prompt=prompt,
            response=result.content[:12_000],
            source_type=source_type,
            source_ref=source_ref,
        )
    except Exception as exc:
        failure = model_failure_metadata(exc)
        try:
            conn.rollback()
        except Exception:
            pass
        _record_safely(
            conn,
            agent_code=POST_MATCH_REPORT_AGENT,
            provider_code=failure["provider_code"],
            model=failure["model"],
            status="failed",
            prompt_length=len(prompt),
            response_length=0,
            duration_ms=round((perf_counter() - started_at) * 1000),
            error_code=failure["error_code"],
        )
        _record_report_attempt(
            conn,
            source_type=source_type,
            source_ref=source_ref,
            status="failed",
            error_code=failure["error_code"],
        )
        return {"status": "failed", "reason": "model_call_failed"}

    _record_safely(
        conn,
        agent_code=POST_MATCH_REPORT_AGENT,
        provider_code=result.provider_code,
        model=result.model,
        status="succeeded",
        prompt_length=len(prompt),
        response_length=len(result.content),
        duration_ms=round((perf_counter() - started_at) * 1000),
    )
    _record_report_attempt(
        conn,
        source_type=source_type,
        source_ref=source_ref,
        status="completed",
        error_code=None,
    )
    return {
        "status": "completed",
        "task": task,
        "agentCode": POST_MATCH_REPORT_AGENT,
        "providerCode": result.provider_code,
        "model": result.model,
    }
