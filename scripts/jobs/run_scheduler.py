"""Local scheduler entrypoint.

Runs long-lived scheduled jobs on the local host.
Codex is used to develop, repair, test, and review this scheduler and its job modules.

Stage 7: all jobs are wrapped with agent audit logging (ai_job_runs table).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date, datetime
from datetime import time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

# Sporttery may add matches or change sale/pool permissions after midnight.
# Refresh at :10 and :40 so the betting terminal never relies on a stale daily snapshot.
OFFICIAL_SCHEDULE_CRON = {"minute": "10,40"}
# Run five minutes after each schedule refresh so newly sellable matches have
# official markets and odds available before the prediction snapshot is written.
MODEL_PREDICTION_CRON = {"minute": "15,45"}
STARTUP_RECOVERY_JOB_CODES = (
    "seed_agent_registry",
    "seed_api_football_registry",
    "seed_stadium_registry",
    "settle_tickets",
    "build_feature_snapshots",
    "run_recommendation_candidate",
)


def _scheduler_timezone_name() -> str:
    """Return the business timezone used by every cron trigger."""
    return os.getenv("FQP_TIMEZONE", "Asia/Shanghai")


def _business_now(timezone_name: str | None = None) -> datetime:
    """Return an aware wall-clock time for scheduler decisions."""
    return datetime.now(ZoneInfo(timezone_name or _scheduler_timezone_name()))


def _should_run_recommendation_catchup(
    now: datetime,
    decision_status: str | None,
) -> bool:
    """Catch up only after 16:00 when today's decision is not terminal."""
    return now.timetz().replace(tzinfo=None) >= clock_time(hour=16) and decision_status not in {
        "purchased",
        "abstained",
    }


def _daily_decision_status(decision_date: date) -> str | None:
    """Read the Agent's terminal decision state for one business date."""
    from apps.backend.src.db import get_db

    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM daily_budget_plans WHERE plan_date = %s",
            (decision_date,),
        )
        row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def _run_recommendation_catchup() -> dict[str, Any]:
    """Recover a missed 16:00 recommendation after a scheduler restart."""
    now = _business_now()
    decision_status = _daily_decision_status(now.date())
    if not _should_run_recommendation_catchup(now, decision_status):
        result = {
            "status": "skipped",
            "reason": "before_cutoff" if now.hour < 16 else "decision_exists",
        }
        print(f"[scheduler] recommendation startup catch-up: {result}")
        return result

    from scripts.jobs.run_recommendation_candidate import run

    result = run()
    print(f"[scheduler] recommendation startup catch-up: {result}")
    return result


def _official_source_enabled() -> bool:
    return os.getenv("OFFICIAL_SOURCE_ENABLED", "true").lower() == "true"


def _odds_dispatch_owner() -> str:
    """Keep the Worker as the single high-frequency odds dispatcher."""
    return os.getenv("FQP_ODDS_DISPATCH_OWNER", "scheduler").lower()


def _audited_job(
    job_code: str, job_name: str, owner_agent: str, fn: Callable[[], Any]
) -> Callable[[], None]:
    """Wrap a job function with agent audit logging (start/finish in ai_job_runs)."""

    # These entrypoints already call start_tracked_job/finish_tracked_job.
    # Wrapping them again here would create duplicate runs and stale outer
    # records with the wrong owner agent.
    self_tracked = {
        "build_feature_snapshots",
        "collect_injury_data",
        "collect_lineup_data",
        "collect_weather",
        "run_model_prediction",
        "run_recommendation_candidate",
        "generate_daily_review",
        "validate_evidence_chain",
        "audit_data_contamination",
        "run_backtest",
    }
    if job_code in self_tracked:
        return fn

    def wrapper() -> None:
        run_id = None
        try:
            from apps.backend.src.db import get_db
            from scripts.agent_storage import (
                finish_job_run,
                recover_interrupted_job_runs,
                start_job_run,
            )

            with get_db() as conn:
                recover_interrupted_job_runs(
                    conn,
                    [job_code],
                    reason=(
                        "superseded by a new scheduler execution after process interruption"
                    ),
                )
                run_id = start_job_run(
                    conn,
                    {
                        "job_code": job_code,
                        "job_name": job_name,
                        "owner_agent": owner_agent,
                        "schedule_type": "cron",
                        "environment": "prod",
                    },
                )
            result = fn()
            if run_id:
                with get_db() as conn:
                    finish_job_run(
                        conn, run_id, "completed", output_refs={"result": str(result)[:500]}
                    )
        except Exception as e:
            if run_id:
                try:
                    from apps.backend.src.db import get_db
                    from scripts.agent_storage import finish_job_run

                    with get_db() as conn:
                        finish_job_run(conn, run_id, "failed", error=str(e)[:1000])
                except Exception:
                    pass
            print(f"[scheduler] {job_code} error: {e}")

    return wrapper


def main() -> None:
    print("FQP local scheduler started.")
    from scripts.local.scheduler_heartbeat import clear_scheduler_pid, write_scheduler_pid

    scheduler_pid = write_scheduler_pid()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        timezone_name = _scheduler_timezone_name()
        scheduler = BackgroundScheduler(timezone=timezone_name)
        print(f"FQP scheduler timezone: {timezone_name}")

        # ----- health heartbeat (always on) -----
        def test_heartbeat() -> None:
            from scripts.local.scheduler_heartbeat import write_heartbeat

            print(f"scheduler heartbeat: {write_heartbeat()}")

        scheduler.add_job(test_heartbeat, "interval", minutes=1, id="test_heartbeat")
        test_heartbeat()

        # ----- Startup recovery: retry critical idempotent jobs until ready -----
        from scripts.jobs.startup_recovery import StartupRecovery

        startup_tasks: dict[str, Callable[[], Any]] = {
            "seed_agent_registry": lambda: __import__(
                "scripts.jobs.seed_agent_registry", fromlist=["run"]
            ).run(),
        }
        if _official_source_enabled():
            startup_tasks.update(
                {
                    "seed_api_football_registry": lambda: __import__(
                        "scripts.jobs.seed_api_football_registry", fromlist=["run"]
                    ).run(),
                    "seed_stadium_registry": lambda: __import__(
                        "scripts.jobs.seed_stadium_registry", fromlist=["run"]
                    ).run(),
                    "settle_tickets": lambda: __import__(
                        "scripts.jobs.settle_tickets", fromlist=["run"]
                    ).run(),
                    "build_feature_snapshots": lambda: __import__(
                        "scripts.jobs.run_feature_snapshot_build", fromlist=["run"]
                    ).run(),
                    "run_recommendation_candidate": _run_recommendation_catchup,
                }
            )
        startup_recovery = StartupRecovery(startup_tasks)

        def run_startup_recovery() -> None:
            result = startup_recovery.run(_business_now(timezone_name))
            print(f"[scheduler] startup recovery: {result}")
            if not result["pending"]:
                scheduler.remove_job("startup_recovery")

        scheduler.add_job(
            run_startup_recovery,
            "interval",
            minutes=1,
            next_run_time=_business_now(timezone_name),
            id="startup_recovery",
        )

        # ----- Stage 2: official data jobs -----
        if _official_source_enabled():
            # Daily: select one valid season per event before accepting new matches.
            scheduler.add_job(
                _audited_job(
                    "reconcile_event_seasons",
                    "赛事中心赛季校准",
                    "crawler_agent",
                    lambda: __import__(
                        "scripts.jobs.reconcile_event_seasons", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=0,
                minute=5,
                id="reconcile_event_seasons",
            )

            # Every 30 min: refresh official matches, sale states, and pool permissions.
            scheduler.add_job(
                lambda: __import__("scripts.jobs.crawl_official_schedule", fromlist=["run"]).run(),
                "cron",
                **OFFICIAL_SCHEDULE_CRON,
                id="crawl_official_schedule",
            )

            if _odds_dispatch_owner() == "scheduler":
                scheduler.add_job(
                    lambda: __import__(
                        "scripts.jobs.run_official_odds_snapshot", fromlist=["run"]
                    ).run(),
                    "interval",
                    minutes=1,
                    id="crawl_official_odds",
                )

            # Hourly from 06:07 through 23:07: traditional lottery crawl.
            scheduler.add_job(
                _audited_job(
                    "crawl_traditional_lottery",
                    "传统足彩采集",
                    "crawler_agent",
                    lambda: __import__(
                        "scripts.jobs.crawl_traditional_lottery", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                minute=7,
                hour="6-23",
                id="crawl_traditional_lottery",
            )

            # Every 30 min: settle finished matches
            scheduler.add_job(
                _audited_job(
                    "settle_finished_matches",
                    "赛果结算",
                    "crawler_agent",
                    lambda: __import__(
                        "scripts.jobs.settle_finished_matches", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                minute="*/30",
                id="settle_finished_matches",
            )

            # ----- Stage 3: feature jobs -----
            # Daily at 02:00: populate teams/leagues
            scheduler.add_job(
                _audited_job(
                    "populate_teams_leagues",
                    "球队联赛映射",
                    "backend_agent",
                    lambda: __import__(
                        "scripts.features.populate_teams_leagues", fromlist=["populate_all"]
                    ).populate_all(),
                ),
                "cron",
                hour=2,
                minute=0,
                id="populate_teams_leagues",
            )

            # Daily after team population: refresh provider aliases used by
            # match-level injury and lineup collection.
            scheduler.add_job(
                _audited_job(
                    "seed_api_football_registry",
                    "API-Football基础标识校准",
                    "feature_agent",
                    lambda: __import__(
                        "scripts.jobs.seed_api_football_registry", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=2,
                minute=3,
                id="seed_api_football_registry_daily",
            )

            # Daily after team population: map supported home teams to stadium coordinates.
            scheduler.add_job(
                _audited_job(
                    "seed_stadium_registry",
                    "球场基础数据校准",
                    "feature_agent",
                    lambda: __import__(
                        "scripts.jobs.seed_stadium_registry", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=2,
                minute=5,
                id="seed_stadium_registry_daily",
            )

            # Every 6 hours: build feature snapshots
            scheduler.add_job(
                _audited_job(
                    "build_feature_snapshots",
                    "特征快照构建",
                    "feature_agent",
                    lambda: __import__(
                        "scripts.jobs.run_feature_snapshot_build", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour="*/6",
                id="build_feature_snapshots",
            )

            # ----- Stage 3b: enrichment data collection jobs -----
            # Daily at 03:00: collect league standings
            scheduler.add_job(
                _audited_job(
                    "collect_standings",
                    "联赛积分榜采集",
                    "crawler_agent",
                    lambda: __import__("scripts.jobs.collect_standings", fromlist=["run"]).run(),
                ),
                "cron",
                hour=3,
                minute=7,
                id="collect_standings",
            )

            # Shortly after midnight: collect current fixture injuries before
            # the day's early matches. Historical-season injuries are never used.
            scheduler.add_job(
                _audited_job(
                    "collect_injury_data",
                    "伤停数据采集",
                    "crawler_agent",
                    lambda: __import__("scripts.jobs.collect_injury_data", fromlist=["run"]).run(),
                ),
                "cron",
                hour=0,
                minute=7,
                id="collect_injury_data",
            )

            # Every 30 minutes after schedule refresh: query only the short
            # pre-match window where confirmed lineups may be published.
            scheduler.add_job(
                _audited_job(
                    "collect_lineup_data",
                    "首发阵容采集",
                    "crawler_agent",
                    lambda: __import__("scripts.jobs.collect_lineup_data", fromlist=["run"]).run(),
                ),
                "cron",
                minute="12,42",
                id="collect_lineup_data",
            )

            # Rebuild feature snapshots after the lineup window and before
            # model prediction at :15/:45, so late evidence reaches decisions.
            scheduler.add_job(
                _audited_job(
                    "build_feature_snapshots",
                    "临场特征快照刷新",
                    "feature_agent",
                    lambda: __import__(
                        "scripts.jobs.run_feature_snapshot_build", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                minute="14,44",
                id="refresh_pre_match_features",
            )

            # Daily at 09:00 and 15:00: collect weather forecasts
            scheduler.add_job(
                _audited_job(
                    "collect_weather",
                    "天气数据采集",
                    "crawler_agent",
                    lambda: __import__("scripts.jobs.collect_weather", fromlist=["run"]).run(),
                ),
                "cron",
                hour="9,15",
                minute=7,
                id="collect_weather",
            )

            # ----- Stage 4: model & recommendation jobs -----
            # Weekly on Monday at 02:00: MLE train model parameters from historical data
            scheduler.add_job(
                _audited_job(
                    "mle_train_models",
                    "MLE模型训练",
                    "model_agent",
                    lambda: __import__("scripts.mle_trainer", fromlist=["run"]).run(),
                ),
                "cron",
                day_of_week="mon",
                hour=2,
                minute=0,
                id="mle_train_models",
            )

            # Daily at 01:00: update Elo ratings from settled matches
            scheduler.add_job(
                _audited_job(
                    "update_elo_ratings",
                    "Elo评分更新",
                    "model_agent",
                    lambda: __import__("scripts.jobs.update_elo_ratings", fromlist=["run"]).run(),
                ),
                "cron",
                hour=1,
                minute=0,
                id="update_elo_ratings",
            )

            # Every 30 minutes: persist a pre-match prediction history snapshot.
            scheduler.add_job(
                _audited_job(
                    "run_model_prediction",
                    "模型预测执行",
                    "model_agent",
                    lambda: __import__("scripts.jobs.run_model_prediction", fromlist=["run"]).run(),
                ),
                "cron",
                **MODEL_PREDICTION_CRON,
                id="run_model_prediction",
            )

            # Daily at 16:00: generate recommendation candidates
            scheduler.add_job(
                _audited_job(
                    "run_recommendation_candidate",
                    "推荐候选生成",
                    "recommendation_agent",
                    lambda: __import__(
                        "scripts.jobs.run_recommendation_candidate", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=16,
                minute=0,
                id="run_recommendation_candidate",
            )

            # ----- Stage 5: settlement and review jobs -----
            # Hourly at :15: settle tickets
            scheduler.add_job(
                _audited_job(
                    "settle_tickets",
                    "票单结算",
                    "review_agent",
                    lambda: __import__("scripts.jobs.settle_tickets", fromlist=["run"]).run(),
                ),
                "cron",
                minute=15,
                id="settle_tickets",
            )

            # Twice hourly after official-result and ticket settlement windows:
            # identify objective cold results from complete pre-match markets.
            scheduler.add_job(
                _audited_job(
                    "detect_upsets",
                    "冷门识别",
                    "review_agent",
                    lambda: __import__("scripts.jobs.detect_upsets", fromlist=["run"]).run(),
                ),
                "cron",
                minute="20,50",
                id="detect_upsets",
            )

            scheduler.add_job(
                _audited_job(
                    "collect_upset_evidence",
                    "冷门证据采集",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.collect_upset_evidence", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                minute="22,52",
                id="collect_upset_evidence",
            )

            scheduler.add_job(
                _audited_job(
                    "generate_upset_reviews",
                    "冷门客观复盘",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.generate_upset_reviews", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                minute="25,55",
                id="generate_upset_reviews",
            )

            # Daily at 08:00: generate review for the previous business day
            scheduler.add_job(
                _audited_job(
                    "generate_daily_review",
                    "日报生成",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.generate_daily_review", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=8,
                minute=0,
                id="generate_daily_review",
            )

            # Weekly at Monday 09:00: generate the previous week's review
            scheduler.add_job(
                _audited_job(
                    "generate_weekly_review",
                    "周报生成",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.generate_periodic_reviews", fromlist=["run_weekly"]
                    ).run_weekly(),
                ),
                "cron",
                day_of_week="mon",
                hour=9,
                minute=0,
                id="generate_weekly_review",
            )

            # Monthly at day 1 10:00: generate the previous month's review
            scheduler.add_job(
                _audited_job(
                    "generate_monthly_review",
                    "月报生成",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.generate_periodic_reviews", fromlist=["run_monthly"]
                    ).run_monthly(),
                ),
                "cron",
                day=1,
                hour=10,
                minute=0,
                id="generate_monthly_review",
            )

            # Daily at 23:45: analyze prediction errors
            scheduler.add_job(
                _audited_job(
                    "analyze_prediction_errors",
                    "错因分析",
                    "review_agent",
                    lambda: __import__(
                        "scripts.jobs.analyze_prediction_errors", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=23,
                minute=45,
                id="analyze_prediction_errors",
            )

            # Daily at 23:40: compute model evaluation metrics (Brier/LogLoss/CLV)
            scheduler.add_job(
                _audited_job(
                    "compute_evaluation_metrics",
                    "模型评估指标计算",
                    "review_agent",
                    lambda: __import__("scripts.evaluation_metrics", fromlist=["run"]).run(),
                ),
                "cron",
                hour=23,
                minute=40,
                id="compute_evaluation_metrics",
            )

            # Weekly on Sunday at 04:00: run full backtest
            scheduler.add_job(
                _audited_job(
                    "run_backtest",
                    "全量回测执行",
                    "backtest_agent",
                    lambda: __import__("scripts.jobs.run_backtest", fromlist=["run"]).run(),
                ),
                "cron",
                day_of_week="sun",
                hour=4,
                minute=7,
                id="run_backtest",
            )

            # ----- Stage 8: operational health & monitoring jobs -----
            # Daily at 23:00: verify latest database backup
            scheduler.add_job(
                _audited_job(
                    "verify_backup",
                    "备份验证",
                    "ops_agent",
                    lambda: __import__("scripts.jobs.verify_backup", fromlist=["run"]).run(),
                ),
                "cron",
                hour=23,
                minute=0,
                id="verify_backup",
            )

            # Daily at 23:30: validate evidence chains
            scheduler.add_job(
                _audited_job(
                    "validate_evidence_chain",
                    "证据链校验",
                    "ops_agent",
                    lambda: __import__(
                        "scripts.jobs.validate_evidence_chain", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=23,
                minute=30,
                id="validate_evidence_chain",
            )

            # Daily at 23:45: audit data contamination
            scheduler.add_job(
                _audited_job(
                    "audit_data_contamination",
                    "数据污染审计",
                    "ops_agent",
                    lambda: __import__(
                        "scripts.jobs.audit_data_contamination", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=23,
                minute=45,
                id="audit_data_contamination",
            )

            # Daily at 23:48: tag simulation ticket errors (框架 §13)
            scheduler.add_job(
                _audited_job(
                    "tag_errors",
                    "错因标签",
                    "review_agent",
                    lambda: __import__("scripts.jobs.tag_errors", fromlist=["run"]).run(),
                ),
                "cron",
                hour=23,
                minute=48,
                id="tag_errors",
            )

            # Daily at 23:50: snapshot competition data
            scheduler.add_job(
                _audited_job(
                    "snapshot_competition",
                    "竞赛快照",
                    "review_agent",
                    lambda: __import__("scripts.jobs.snapshot_competition", fromlist=["run"]).run(),
                ),
                "cron",
                hour=23,
                minute=50,
                id="snapshot_competition",
            )

            # Daily at 23:55: collect health metrics (runs last to aggregate all daily results)
            scheduler.add_job(
                _audited_job(
                    "collect_health_metrics",
                    "健康指标采集",
                    "ops_agent",
                    lambda: __import__(
                        "scripts.jobs.collect_health_metrics", fromlist=["run"]
                    ).run(),
                ),
                "cron",
                hour=23,
                minute=55,
                id="collect_health_metrics",
            )

            # Daily at 23:59: reset agent competition budget
            scheduler.add_job(
                _audited_job(
                    "reset_agent_budget",
                    "竞赛代理资金重置",
                    "review_agent",
                    lambda: __import__("scripts.jobs.reset_agent_budget", fromlist=["run"]).run(),
                ),
                "cron",
                hour=23,
                minute=59,
                id="reset_agent_budget",
            )

            # Weekly on Sunday at 00:00: snapshot runtime environment
            scheduler.add_job(
                _audited_job(
                    "snapshot_runtime",
                    "运行时环境快照",
                    "ops_agent",
                    lambda: __import__("scripts.local.snapshot_runtime", fromlist=["run"]).run(),
                ),
                "cron",
                day_of_week="sun",
                hour=0,
                minute=0,
                id="snapshot_runtime",
            )

            job_ids = ", ".join(job.id for job in scheduler.get_jobs())
            print(f"APScheduler started with {len(scheduler.get_jobs())} jobs: {job_ids}")
        else:
            print(
                "APScheduler started with 2 jobs: test_heartbeat, startup_recovery. "
                "Official data jobs disabled (OFFICIAL_SOURCE_ENABLED != true)."
            )

        scheduler.start()

        while True:
            time.sleep(3600)

    except ImportError:
        print("APScheduler not available; falling back to basic sleep loop.")
        while True:
            print(f"scheduler heartbeat: {_business_now().isoformat(timespec='seconds')}")
            time.sleep(3600)
    finally:
        clear_scheduler_pid(scheduler_pid)


if __name__ == "__main__":
    main()
