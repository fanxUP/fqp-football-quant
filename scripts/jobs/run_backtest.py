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
import os
import sys
from datetime import timedelta
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.agents.task_queue import finish_tracked_job, start_tracked_job  # noqa: E402
from scripts.backtest_engine import BacktestConfig, run_backtest_from_config  # noqa: E402
from scripts.business_time import business_today  # noqa: E402


def _default_config(name: str, model_names: list[str] | None = None) -> BacktestConfig:
    """构建默认回测配置。

    默认：过去 2 年的数据，90 天 walk-forward 窗口，strong 信号。
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


def run_full_backtest(conn: Any, dry_run: bool = False) -> dict[str, Any]:
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

    result = run_backtest_from_config(conn, config, store=True)
    return {
        "status": result.get("status", "ok"),
        "run_id": result.get("run_id"),
        "models_tested": model_names,
        "total_bets": result.get("total_bets", 0),
        "total_windows": result.get("total_windows", 0),
        "aggregate": {
            m: {k: v for k, v in metrics.items() if k != "equity_curve"}
            for m, metrics in result.get("aggregate", {}).items()
        },
    }


def run_model_backtest(
    conn: Any,
    model_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """对单个模型运行回测（用于模型上线前验证）。"""
    if dry_run:
        return {"status": "dry_run", "message": f"backtest for {model_name} (dry run)"}

    config = _default_config(
        name=f"{model_name}-回测-{business_today().isoformat()}",
        model_names=[model_name],
    )

    result = run_backtest_from_config(conn, config, store=True)

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
    }


def run_parameter_sweep(
    conn: Any,
    base_config: BacktestConfig,
    param_grid: dict[str, list],
    dry_run: bool = False,
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

    combinations = list(product(*values))

    results = []
    best_roi = float("-inf")
    best_result = None

    for combo in combinations:
        param_dict = dict(zip(keys, combo, strict=False))
        cfg_dict = base_config.to_dict()
        cfg_dict.update(param_dict)
        cfg_dict["name"] = f"sweep-{'-'.join(f'{k}={v}' for k, v in param_dict.items())}"
        cfg = BacktestConfig.from_dict(cfg_dict)

        result = run_backtest_from_config(conn, cfg, store=True)

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


def _run_impl(
    model_name: str | None = None,
    sweep: bool = False,
    dry_run: bool = False,
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

    with get_db() as conn:
        if sweep:
            # 参数扫描模式
            base = _default_config("参数扫描")
            grid: dict[str, list[Any]] = {
                "min_model_prob": [0.30, 0.35, 0.40],
                "odds_min": [1.5, 2.0],
                "signal_strength": ["strong", "all"],
            }
            return run_parameter_sweep(conn, base, grid)

        if model_name:
            return run_model_backtest(conn, model_name)

    return run_full_backtest(conn)


def run(
    model_name: str | None = None,
    sweep: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run backtest and persist its multi-agent execution record."""
    run_id = start_tracked_job(
        "backtest",
        "backtest_agent",
        {"model_name": model_name, "sweep": sweep, "dry_run": dry_run},
    )
    try:
        result = _run_impl(model_name=model_name, sweep=sweep, dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
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
