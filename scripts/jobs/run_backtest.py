"""回测 Job — 定时或手动触发回测运行。

支持三种模式：
  1. 全量回测：对全部活跃模型在全部历史数据上运行
  2. 模型回测：对指定模型运行（用于模型上线前验证）
  3. 参数扫描：对多个配置组合批量回测

Job 调度：每周日 04:00（错开高峰时段）

使用方式：
  python -m scripts.jobs.run_backtest                  # 全量回测
  python -m scripts.jobs.run_backtest --model maher_poisson  # 单模型
  python -m scripts.jobs.run_backtest --dry-run              # 空跑
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from contextlib import nullcontext
from datetime import timedelta
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.agent_storage import start_job_run  # noqa: E402
from scripts.backtest_engine import BacktestConfig, run_backtest_from_config  # noqa: E402
from scripts.backtest_job_execution import (  # noqa: E402
    EXECUTION_PROTOCOL,
    backtest_execution,
    reconcile_backtest_job,
)
from scripts.business_time import business_today  # noqa: E402

_LOG = logging.getLogger(__name__)


def _default_config(name: str, model_names: list[str] | None = None) -> BacktestConfig:
    """构建默认回测配置。

    默认：回放过去 2 年已保存的赛前预测，全部信号，最低概率 0.01。
    不重新训练模型（walk_forward=False）；窗口参数保留为 365 天。
    """
    today = business_today()
    two_years_ago = today - timedelta(days=730)

    return BacktestConfig(
        name=name,
        description=f"自动回测 — {today.isoformat()}",
        time_start=two_years_ago.isoformat(),
        time_end=today.isoformat(),
        play_types=["spf"],
        model_names=model_names,
        walk_forward=False,
        train_window_days=365,
        test_window_days=365,
        step_days=30,
        stake_per_bet=1.0,
        min_model_prob=0.01,
        signal_strength="all",
    )


def _get_active_model_names(conn: Any) -> list[str]:
    """获取所有活跃模型的名称。"""
    with conn.cursor() as cur:
        cur.execute("SELECT model_name FROM model_versions WHERE is_active = true")
        return [row[0] for row in cur.fetchall()]


def run_full_backtest(
    conn: Any, dry_run: bool = False, *, ai_job_run_id: int | None = None
) -> dict[str, Any]:
    """对所有活跃模型运行全量回测。"""
    if dry_run:
        return {"status": "dry_run", "message": "full backtest (dry run)"}

    model_names = _get_active_model_names(conn)
    if not model_names:
        return {"status": "error", "error": "no active models found"}

    config = _default_config(
        name=f"全量回测-{business_today().isoformat()}",
        model_names=model_names,
    )

    result = run_backtest_from_config(conn, config, store=True, ai_job_run_id=ai_job_run_id)
    return {
        "status": result.get("status", "ok"),
        "run_id": result.get("run_id"),
        "models_tested": model_names,
        "total_bets": result.get("total_bets", 0),
        "total_windows": result.get("total_windows", 0),
        **({"store_error": result["store_error"]} if "store_error" in result else {}),
        "aggregate": {
            m: {k: v for k, v in metrics.items() if k != "equity_curve"}
            for m, metrics in result.get("aggregate", {}).items()
        },
    }


def run_model_backtest(
    conn: Any,
    model_name: str,
    dry_run: bool = False,
    *,
    ai_job_run_id: int | None = None,
) -> dict[str, Any]:
    """对单个模型运行回测（用于模型上线前验证）。"""
    if dry_run:
        return {"status": "dry_run", "message": f"backtest for {model_name} (dry run)"}

    config = _default_config(
        name=f"{model_name}-回测-{business_today().isoformat()}",
        model_names=[model_name],
    )

    result = run_backtest_from_config(conn, config, store=True, ai_job_run_id=ai_job_run_id)

    # 检查模型上线门槛
    aggregate = result.get("aggregate", {})
    model_metrics = aggregate.get(model_name, {})

    n_bets = model_metrics.get("n_bets", 0)
    checks = {
        "min_samples": n_bets >= 1000,
        "positive_roi": (model_metrics.get("roi") or -1) > 0,
        "acceptable_drawdown": (model_metrics.get("max_drawdown_pct") or 100) < 30,
        "reasonable_hit_rate": (model_metrics.get("hit_rate") or 0) > 0.30,
    }

    return {
        "status": result.get("status", "ok"),
        "run_id": result.get("run_id"),
        "model_name": model_name,
        "metrics": {k: v for k, v in model_metrics.items() if k != "equity_curve"},
        "production_gate": checks,
        "production_ready": all(checks.values()),
        "total_bets": result.get("total_bets", 0),
        **({"store_error": result["store_error"]} if "store_error" in result else {}),
    }


def run_parameter_sweep(
    conn: Any,
    base_config: BacktestConfig,
    param_grid: dict[str, list],
    dry_run: bool = False,
    *,
    ai_job_run_id: int | None = None,
) -> dict[str, Any]:
    """参数扫描：对多个配置组合批量回测。

    Args:
        conn: DB 连接
        base_config: 基础配置
        param_grid: 参数网格，e.g. {"min_model_prob": [0.30, 0.35, 0.40], "odds_min": [1.5, 2.0]}
        dry_run: 空跑模式

    Returns:
        {"runs": [...], "best": {...}}
    """
    if dry_run:
        return {"status": "dry_run", "message": "parameter sweep (dry run)"}

    # 生成参数组合（笛卡尔积）
    keys = list(param_grid.keys())
    values = list(param_grid.values())

    from itertools import product

    if any(key not in BacktestConfig.__dataclass_fields__ for key in keys):
        raise ValueError("参数扫描包含不支持的配置项")
    if any(not isinstance(value, list) or not value for value in values):
        raise ValueError("参数扫描的每项必须是非空列表")
    if math.prod(map(len, values)) > 100:
        raise ValueError("参数扫描最多允许 100 组")
    combinations = list(product(*values))
    configs = []
    for combo in combinations:
        params = dict(zip(keys, combo, strict=True))
        generated_name = f"sweep-{'-'.join(f'{k}={v}' for k, v in params.items())}"
        configs.append(
            BacktestConfig.from_dict({**base_config.to_dict(), **params, "name": generated_name})
        )

    results: list[dict[str, Any]] = []
    best_roi = float("-inf")
    best_result = None

    for combo, cfg in zip(combinations, configs, strict=True):
        param_dict = dict(zip(keys, combo, strict=False))
        result = run_backtest_from_config(conn, cfg, store=True, ai_job_run_id=ai_job_run_id)
        if result.get("status") == "store_failed":
            return {
                "status": "store_failed",
                "run_id": result.get("run_id"),
                "store_error": result.get("store_error"),
                "total_runs": len(results) + 1,
                "param_keys": keys,
                "best": best_result,
            }

        # 提取最佳 ROI
        for model_name, metrics in result.get("aggregate", {}).items():
            roi = metrics.get("roi")
            if roi is not None and roi > best_roi:
                best_roi = roi
                best_result = {
                    "run_id": result.get("run_id"),
                    "model_name": model_name,
                    "params": param_dict,
                    "roi": roi,
                    "hit_rate": metrics.get("hit_rate"),
                    "n_bets": metrics.get("n_bets"),
                }

        results.append(
            {
                "params": param_dict,
                "run_id": result.get("run_id"),
                "aggregate": {
                    m: {k: v for k, v in metrics.items() if k != "equity_curve"}
                    for m, metrics in result.get("aggregate", {}).items()
                },
            }
        )

    return {
        "status": "ok",
        "total_runs": len(results),
        "param_keys": keys,
        "best": best_result,
    }


# —— Job entry point ——


def _sweep_grid() -> dict[str, list[Any]]:
    return {
        "min_model_prob": [0.30, 0.35, 0.40],
        "odds_min": [1.5, 2.0],
        "signal_strength": ["strong", "all"],
    }


def _run_impl(
    model_name: str | None = None,
    sweep: bool = False,
    dry_run: bool = False,
    *,
    execution_conn: Any = None,
    ai_job_run_id: int | None = None,
) -> dict[str, Any]:
    """Job 入口：从调度器或 CLI 调用。

    Args:
        model_name: 单模型回测（None = 全量）
        sweep: 是否运行参数扫描
        dry_run: 空跑模式
    """
    if dry_run:
        return {"status": "dry_run", "message": "backtest job (dry run)"}

    from apps.backend.src.db import get_db

    with nullcontext(execution_conn) if execution_conn is not None else get_db() as conn:
        if sweep:
            # 参数扫描模式
            base = _default_config("参数扫描")
            return run_parameter_sweep(conn, base, _sweep_grid(), ai_job_run_id=ai_job_run_id)

        if model_name:
            return run_model_backtest(conn, model_name, ai_job_run_id=ai_job_run_id)

        return run_full_backtest(conn, ai_job_run_id=ai_job_run_id)


def run(
    model_name: str | None = None,
    sweep: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scheduled/CLI entry, sharing ownership with manual API backtests."""
    return _run_owned(model_name=model_name, sweep=sweep, dry_run=dry_run)


def run_config(config: BacktestConfig) -> dict[str, Any]:
    """Manual API entry; use the same execution protocol and writing session."""
    return _run_owned(config=config)


def _run_owned(
    *,
    config: BacktestConfig | None = None,
    model_name: str | None = None,
    sweep: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if config is not None:
        config.validate()
    with backtest_execution() as conn:
        if conn is None:
            return {"status": "skipped", "reason": "backtest_execution_in_progress"}
        expected = 0 if dry_run else math.prod(map(len, _sweep_grid().values())) if sweep else 1
        job_id = start_job_run(
            conn,
            {
                "job_code": "backtest",
                "job_name": "backtest",
                "owner_agent": "backtest_agent",
                "schedule_type": "manual" if config is not None else "scheduled",
                "environment": "local",
                "input_snapshot_refs": {
                    "execution_protocol": EXECUTION_PROTOCOL,
                    "expected_runs": expected,
                    "model_name": model_name,
                    "sweep": sweep,
                    "dry_run": dry_run,
                },
            },
        )
        if job_id is None:
            raise RuntimeError("backtest audit owner ID was not returned")
        return _execute_owned(conn, job_id, config, model_name, sweep, dry_run)


def _execute_owned(conn, job_id, config, model_name, sweep, dry_run):
    try:
        if config is not None:
            result = run_backtest_from_config(conn, config, store=True, ai_job_run_id=job_id)
        else:
            result = _run_impl(
                model_name=model_name,
                sweep=sweep,
                dry_run=dry_run,
                execution_conn=conn,
                ai_job_run_id=job_id,
            )
        reconcile_backtest_job(
            conn, job_id, result=result, error=result.get("store_error") or result.get("error")
        )
        return result
    except Exception as exc:
        try:
            conn.rollback()
            reconcile_backtest_job(conn, job_id, error=str(exc))
        except Exception:
            _LOG.exception(
                "Backtest reconciliation failed; leaving durable facts for the next owner"
            )
        raise


# —— CLI ——

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="回测 Job")
    p.add_argument("--model", help="单模型回测（模型名称）")
    p.add_argument("--sweep", action="store_true", help="参数扫描模式")
    p.add_argument("--dry-run", action="store_true", help="空跑模式")
    args = p.parse_args()

    result = run(model_name=args.model, sweep=args.sweep, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
