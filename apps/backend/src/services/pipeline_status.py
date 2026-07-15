"""Normalize scheduler and source records for the operations dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class JobDefinition:
    name: str
    schedule: str
    category: str
    aliases: tuple[str, ...] = ()


JOB_DEFINITIONS: dict[str, JobDefinition] = {
    "reconcile_event_seasons": JobDefinition("赛事中心赛季校准", "每日 00:06", "official"),
    "official_schedule": JobDefinition("官方赛程采集", "每30分钟", "official", ("crawl_official_schedule",)),
    "official_odds_snapshot": JobDefinition("赔率快照采集", "按开盘/每30分钟/开赛时", "official", ("crawl_official_odds",)),
    "crawl_traditional_lottery": JobDefinition("传统足彩采集", "每小时 07 分", "official"),
    "settle_finished_matches": JobDefinition("赛果采集", "每30分钟", "official"),
    "populate_teams_leagues": JobDefinition("球队联赛映射", "每日 02:00", "official"),
    "feature_snapshot_build": JobDefinition("特征快照构建", "每6小时", "model", ("build_feature_snapshots",)),
    "collect_standings": JobDefinition("联赛积分榜采集", "每日 03:07", "official"),
    "injury_collection": JobDefinition("伤停数据采集", "每日 08:07", "official", ("collect_injury_data",)),
    "lineup_collection": JobDefinition("首发阵容采集", "每日 10:07/14:07", "official", ("collect_lineup_data",)),
    "weather_collection": JobDefinition("天气数据采集", "每日 09:07/15:07", "official", ("collect_weather",)),
    "mle_train_models": JobDefinition("MLE模型训练", "每周一 02:00", "model"),
    "update_elo_ratings": JobDefinition("Elo评分更新", "每日 01:00", "model"),
    "model_prediction": JobDefinition("模型预测执行", "每6小时", "model", ("run_model_prediction",)),
    "recommendation_candidate": JobDefinition("推荐候选生成", "每日 16:00", "model", ("run_recommendation_candidate",)),
    "settle_tickets": JobDefinition("票单结算", "每小时 15 分", "official"),
    "daily_review": JobDefinition("日报生成", "每日 00:00", "review", ("generate_daily_review",)),
    "generate_weekly_review": JobDefinition("周报生成", "每周一 09:00", "review"),
    "generate_monthly_review": JobDefinition("月报生成", "每月1日 09:30", "review"),
    "analyze_prediction_errors": JobDefinition("错因分析", "每日 23:45", "review"),
    "compute_evaluation_metrics": JobDefinition("模型评估指标计算", "每日 23:40", "model"),
    "backtest": JobDefinition("全量回测执行", "每周日 04:07", "model", ("run_backtest",)),
    "verify_backup": JobDefinition("备份验证", "每日 23:00", "review"),
    "evidence_chain_validation": JobDefinition("证据链校验", "每日 23:30", "review", ("validate_evidence_chain",)),
    "data_contamination_audit": JobDefinition("数据污染审计", "每日 23:45", "review", ("audit_data_contamination",)),
    "tag_errors": JobDefinition("错因标签", "每日 23:48", "review"),
    "snapshot_competition": JobDefinition("竞赛快照", "每日 23:50", "review"),
    "collect_health_metrics": JobDefinition("健康指标采集", "每日 23:55", "review"),
    "reset_agent_budget": JobDefinition("竞赛代理资金重置", "每日 23:59", "review"),
    "snapshot_runtime": JobDefinition("运行时环境快照", "每周日 08:00", "review"),
}

SUCCESS_STATUSES = {"completed", "ok", "success"}
FAILED_STATUSES = {"error", "failed"}


def utc_iso(value: Any) -> str | None:
    """Serialize PostgreSQL's UTC-naive operational timestamps explicitly."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _normalize_job_status(status: object) -> str:
    normalized = str(status or "unknown").lower()
    if normalized in SUCCESS_STATUSES:
        return "success"
    if normalized in FAILED_STATUSES:
        return "failed"
    if normalized == "running":
        return "running"
    if normalized in {"skipped", "abstained", "dry_run"}:
        return "skipped"
    return "unknown"


def get_pipeline_snapshot(conn: Any) -> dict[str, list[dict[str, Any]]]:
    """Return only current scheduler jobs with stable names and UTC timestamps."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (source_name, source_type)
                      id, source_name, source_type, status, last_success_time,
                      last_failure_time, failure_count, latency_ms
               FROM data_source_health
               ORDER BY source_name, source_type, id DESC"""
        )
        source_rows = cur.fetchall()

        active_codes = [
            code
            for canonical, definition in JOB_DEFINITIONS.items()
            for code in (canonical, *definition.aliases)
        ]
        cur.execute(
            """SELECT DISTINCT ON (job_code)
                      id, job_code, status, finished_at, error_message
               FROM ai_job_runs
               WHERE job_code = ANY(%s)
               ORDER BY job_code, id DESC""",
            (active_codes,),
        )
        job_rows = cur.fetchall()

    typed_source_names = {
        str(row[1])
        for row in source_rows
        if str(row[2]) in {"schedule", "odds", "results"}
    }
    visible_source_rows = [
        row
        for row in source_rows
        if not (str(row[2]) == "official" and str(row[1]) in typed_source_names)
    ]
    sources = [
        {
            "name": row[1],
            "source_type": row[2],
            "status": row[3],
            "last_success": utc_iso(row[4]),
            "last_failure": utc_iso(row[5]),
            "failures": row[6],
            "latency_ms": row[7],
        }
        for row in visible_source_rows
    ]

    latest_by_code = {str(row[1]): row for row in job_rows}
    jobs: list[dict[str, Any]] = []
    for canonical, definition in JOB_DEFINITIONS.items():
        candidates = [
            latest_by_code[code]
            for code in (canonical, *definition.aliases)
            if code in latest_by_code
        ]
        if not candidates:
            continue
        latest = max(candidates, key=lambda row: int(row[0]))
        jobs.append(
            {
                "code": canonical,
                "name": definition.name,
                "status": _normalize_job_status(latest[2]),
                "finished_at": utc_iso(latest[3]),
                "error": latest[4],
                "schedule": definition.schedule,
                "category": definition.category,
            }
        )

    return {"sources": sources, "jobs": jobs}
