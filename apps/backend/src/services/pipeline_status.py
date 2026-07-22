"""Normalize scheduler and source records for the operations dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class JobDefinition:
    name: str
    schedule: str
    category: str
    aliases: tuple[str, ...] = ()
    max_age: timedelta | None = None


JOB_DEFINITIONS: dict[str, JobDefinition] = {
    "reconcile_event_seasons": JobDefinition(
        "赛事中心赛季校准", "每日 00:05", "official", max_age=timedelta(hours=30)
    ),
    "official_schedule": JobDefinition(
        "官方赛程采集",
        "每30分钟（:10/:40）",
        "official",
        ("crawl_official_schedule",),
        timedelta(minutes=90),
    ),
    "official_odds_snapshot": JobDefinition(
        "赔率快照采集",
        "每分钟检查；开盘/每30分钟/开赛时采集",
        "official",
        ("crawl_official_odds",),
        timedelta(minutes=5),
    ),
    "crawl_traditional_lottery": JobDefinition(
        "传统足彩采集", "每日 06:07-23:07 每小时", "official", max_age=timedelta(hours=8)
    ),
    "settle_finished_matches": JobDefinition(
        "赛果采集", "每30分钟", "official", max_age=timedelta(minutes=90)
    ),
    "populate_teams_leagues": JobDefinition(
        "球队联赛映射", "每日 02:00", "official", max_age=timedelta(hours=30)
    ),
    "feature_snapshot_build": JobDefinition(
        "特征快照构建", "每6小时", "model", ("build_feature_snapshots",), timedelta(hours=8)
    ),
    "collect_standings": JobDefinition(
        "联赛积分榜采集", "每日 03:07", "official", max_age=timedelta(hours=30)
    ),
    "injury_collection": JobDefinition(
        "伤停数据采集", "每日 00:07", "official", ("collect_injury_data",), timedelta(hours=30)
    ),
    "lineup_collection": JobDefinition(
        "首发阵容采集",
        "每30分钟（:12/:42）",
        "official",
        ("collect_lineup_data",),
        timedelta(hours=22),
    ),
    "weather_collection": JobDefinition(
        "天气数据采集", "每日 09:07/15:07", "official", ("collect_weather",), timedelta(hours=22)
    ),
    "mle_train_models": JobDefinition(
        "MLE模型训练", "每周一 02:00", "model", max_age=timedelta(days=8)
    ),
    "update_elo_ratings": JobDefinition(
        "Elo评分更新", "每日 01:00", "model", max_age=timedelta(hours=30)
    ),
    "model_prediction": JobDefinition(
        "模型预测执行",
        "每30分钟（官方赛程刷新后5分钟）",
        "model",
        ("run_model_prediction",),
        timedelta(hours=2),
    ),
    "recommendation_candidate": JobDefinition(
        "推荐候选生成",
        "每日 16:00（启动时补偿）",
        "model",
        ("run_recommendation_candidate",),
        timedelta(hours=30),
    ),
    "settle_tickets": JobDefinition(
        "票单结算", "每小时 15 分", "official", max_age=timedelta(hours=3)
    ),
    "daily_review": JobDefinition(
        "日报生成", "每日 08:00", "review", ("generate_daily_review",), timedelta(hours=30)
    ),
    "generate_weekly_review": JobDefinition(
        "周报生成", "每周一 09:00", "review", max_age=timedelta(days=8)
    ),
    "generate_monthly_review": JobDefinition(
        "月报生成", "每月1日 10:00", "review", max_age=timedelta(days=35)
    ),
    "analyze_prediction_errors": JobDefinition(
        "错因分析", "每日 23:45", "review", max_age=timedelta(hours=30)
    ),
    "compute_evaluation_metrics": JobDefinition(
        "模型评估指标计算", "每日 23:40", "model", max_age=timedelta(hours=30)
    ),
    "backtest": JobDefinition(
        "全量回测执行", "每周日 04:07", "model", ("run_backtest",), timedelta(days=8)
    ),
    "verify_backup": JobDefinition("备份验证", "每日 23:00", "review", max_age=timedelta(hours=30)),
    "evidence_chain_validation": JobDefinition(
        "证据链校验", "每日 23:30", "review", ("validate_evidence_chain",), timedelta(hours=30)
    ),
    "data_contamination_audit": JobDefinition(
        "数据污染审计", "每日 23:45", "review", ("audit_data_contamination",), timedelta(hours=30)
    ),
    "tag_errors": JobDefinition("错因标签", "每日 23:48", "review", max_age=timedelta(hours=30)),
    "snapshot_competition": JobDefinition(
        "竞赛快照", "每日 23:50", "review", max_age=timedelta(hours=30)
    ),
    "collect_health_metrics": JobDefinition(
        "健康指标采集", "每日 23:55", "review", max_age=timedelta(hours=30)
    ),
    "reset_agent_budget": JobDefinition(
        "竞赛代理资金重置", "每日 23:59", "review", max_age=timedelta(hours=30)
    ),
    "snapshot_runtime": JobDefinition(
        "运行时环境快照", "每周日 00:00", "review", max_age=timedelta(days=8)
    ),
}

SOURCE_MAX_AGES: dict[tuple[str, str], timedelta] = {
    ("sporttery", "odds"): timedelta(minutes=5),
    ("sporttery", "results"): timedelta(minutes=90),
    ("sporttery", "traditional_lottery"): timedelta(hours=8),
    ("sporttery", "schedule"): timedelta(minutes=90),
    ("sporttery_v2", "schedule"): timedelta(minutes=90),
}

SUCCESS_STATUSES = {"completed", "ok", "success"}
FAILED_STATUSES = {"error", "failed"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_stale(value: Any, max_age: timedelta | None, now: datetime) -> bool:
    if max_age is None:
        return False
    timestamp = _as_utc(value)
    if timestamp is None:
        return True
    age = now - timestamp
    return age < -timedelta(minutes=5) or age > max_age


def utc_iso(value: Any) -> str | None:
    """Serialize PostgreSQL's UTC-naive operational timestamps explicitly."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
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


def _job_result(output_refs: object) -> dict[str, Any] | None:
    if isinstance(output_refs, str):
        try:
            output_refs = json.loads(output_refs)
        except json.JSONDecodeError:
            return None
    if not isinstance(output_refs, dict):
        return None
    result = output_refs.get("result", output_refs)
    if not isinstance(result, dict):
        return None
    return result


def _job_quality(output_refs: object) -> tuple[str | None, str | None]:
    result = _job_result(output_refs)
    if result is None:
        return None, None
    quality_status = str(result.get("quality_status") or "") or None
    quality_note = str(result.get("quality_note") or "") or None
    if not quality_note and result.get("average_completeness") is not None:
        quality_note = f"平均特征完整度 {float(result['average_completeness']):.1f}%"
    return quality_status, quality_note


def _job_result_message(output_refs: object) -> str | None:
    result = _job_result(output_refs)
    if result is None:
        return None
    return str(result.get("message") or result.get("error") or "") or None


def _canonical_source_rows(source_rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Merge the uniform schedule source and its legacy fallback into one status."""
    schedule_rows = [
        row
        for row in source_rows
        if str(row[2]) == "schedule" and str(row[1]) in {"sporttery", "sporttery_v2"}
    ]
    if not schedule_rows:
        return source_rows

    def event_key(row: tuple[Any, ...]) -> tuple[datetime, int]:
        timestamps = [_as_utc(row[4]), _as_utc(row[5])]
        latest = max(
            (value for value in timestamps if value is not None),
            default=datetime.min.replace(tzinfo=UTC),
        )
        return latest, int(row[0])

    selected_row = schedule_rows[0]
    for candidate in schedule_rows[1:]:
        if event_key(candidate) > event_key(selected_row):
            selected_row = candidate
    selected = list(selected_row)
    selected[1] = "sporttery"
    canonical_schedule = tuple(selected)

    merged: list[tuple[Any, ...]] = []
    schedule_inserted = False
    for row in source_rows:
        is_schedule_variant = str(row[2]) == "schedule" and str(row[1]) in {
            "sporttery",
            "sporttery_v2",
        }
        if not is_schedule_variant:
            merged.append(row)
        elif not schedule_inserted:
            merged.append(canonical_schedule)
            schedule_inserted = True
    return merged


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
        source_rows = _canonical_source_rows(cur.fetchall())

        active_codes = [
            code
            for canonical, definition in JOB_DEFINITIONS.items()
            for code in (canonical, *definition.aliases)
        ]
        cur.execute(
            """SELECT DISTINCT ON (job_code)
                      id, job_code, status, finished_at, error_message, output_refs
               FROM ai_job_runs
               WHERE job_code = ANY(%s)
                 AND COALESCE((input_snapshot_refs->>'dry_run')::boolean, false) = false
               ORDER BY job_code, id DESC""",
            (active_codes,),
        )
        job_rows = cur.fetchall()

    explicit_source_names = {str(row[1]) for row in source_rows if str(row[2]) != "official"}
    visible_source_rows = [
        row
        for row in source_rows
        if (str(row[1]), str(row[2])) in SOURCE_MAX_AGES
        and not (str(row[2]) == "official" and str(row[1]) in explicit_source_names)
    ]
    now = _utc_now()
    sources = []
    for row in visible_source_rows:
        source_status = str(row[3] or "unknown").lower()
        source_key = (str(row[1]), str(row[2]))
        event_time = row[4] if source_status == "ok" else row[5]
        if source_status == "ok" and _is_stale(event_time, SOURCE_MAX_AGES.get(source_key), now):
            source_status = "stale"
        sources.append(
            {
                "name": row[1],
                "source_type": row[2],
                "status": source_status,
                "last_success": utc_iso(row[4]),
                "last_failure": utc_iso(row[5]),
                "failures": row[6],
                "latency_ms": row[7],
            }
        )

    latest_by_code = {str(row[1]): row for row in job_rows}
    jobs: list[dict[str, Any]] = []
    for canonical, definition in JOB_DEFINITIONS.items():
        candidates = [
            latest_by_code[code]
            for code in (canonical, *definition.aliases)
            if code in latest_by_code
        ]
        if not candidates:
            jobs.append(
                {
                    "code": canonical,
                    "name": definition.name,
                    "status": "pending",
                    "finished_at": None,
                    "error": None,
                    "detail": None,
                    "schedule": definition.schedule,
                    "category": definition.category,
                }
            )
            continue
        latest = max(candidates, key=lambda row: int(row[0]))
        status = _normalize_job_status(latest[2])
        if status == "success" and _is_stale(latest[3], definition.max_age, now):
            status = "stale"
        quality_status, quality_note = _job_quality(latest[5])
        error_message = latest[4] or _job_result_message(latest[5])
        if status == "success" and quality_status == "degraded":
            status = "degraded"
        jobs.append(
            {
                "code": canonical,
                "name": definition.name,
                "status": status,
                "finished_at": utc_iso(latest[3]),
                "error": error_message,
                "detail": quality_note,
                "schedule": definition.schedule,
                "category": definition.category,
            }
        )

    return {"sources": sources, "jobs": jobs}
