"""Optional, failure-isolated model interpretation for completed reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from apps.backend.src.services.agent_workspace_store import (
    create_workspace_task,
    has_workspace_task_for_source,
)
from apps.backend.src.services.model_gateway import invoke_agent_model
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import list_agent_model_bindings

POST_MATCH_REPORT_AGENT = "post_match_report_agent"
POST_MATCH_REPORT_AUTOMATION_KEY = "post_match_report"
_MAX_SNAPSHOT_CHARS = 6_000


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
            item for item in list_agent_model_bindings(conn)
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
    material = json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True)
    truncated = len(material) > _MAX_SNAPSHOT_CHARS
    material = material[:_MAX_SNAPSHOT_CHARS]
    return (
        "请基于以下后端冻结的赛后报告材料，生成中文复盘。\n"
        "必须分开陈述：已确认事实、模型与赔率偏差、冷门/异常、证据缺口、待人工核验项。\n"
        "不得新增外部事实、不得给出投注指令、不得修改模型或业务记录。模型输出仅供人工核验。\n"
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
    except Exception:
        _record_safely(
            conn,
            agent_code=POST_MATCH_REPORT_AGENT,
            provider_code=None,
            model=None,
            status="failed",
            prompt_length=len(prompt),
            response_length=0,
            duration_ms=round((perf_counter() - started_at) * 1000),
            error_code="MODEL_CALL_FAILED",
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
    return {
        "status": "completed",
        "task": task,
        "agentCode": POST_MATCH_REPORT_AGENT,
        "providerCode": result.provider_code,
        "model": result.model,
    }
