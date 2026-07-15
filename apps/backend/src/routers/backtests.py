"""Backtest center endpoints: list, detail, equity curve, create (Stage 11)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.backtest_engine import BacktestConfig, run_backtest_from_config
from scripts.business_time import business_today

router = APIRouter(tags=["backtests"])


@router.get("/api/backtests")
def list_backtests(
    limit: int = Query(20),
    offset: int = Query(0),
):
    """List recent backtest runs."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, config, status,
                          started_at, finished_at, error_message, created_at
                   FROM backtest_runs
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            columns = [desc[0] for desc in cur.description]
            runs = [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

            # Get total count
            cur.execute("SELECT COUNT(*) FROM backtest_runs")
            total = cur.fetchone()[0]

    # Convert dates to strings
    for r in runs:
        for k in ("started_at", "finished_at", "created_at"):
            if r.get(k):
                r[k] = str(r[k])

    return {"runs": runs, "total": total, "limit": limit, "offset": offset}


@router.get("/api/backtests/{run_id}")
def get_backtest_detail(run_id: int):
    """Get a single backtest run with windows and per-model results."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Run metadata
            cur.execute(
                """SELECT id, name, description, config, status,
                          started_at, finished_at, error_message, created_at
                   FROM backtest_runs WHERE id = %s""",
                (run_id,),
            )
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            if not row:
                return {"error": "not found", "run_id": run_id}

            run = dict(zip(columns, row, strict=False))
            for k in ("started_at", "finished_at", "created_at"):
                if run.get(k):
                    run[k] = str(run[k])

            # Windows
            cur.execute(
                """SELECT window_index, train_start_date, train_end_date,
                          test_start_date, test_end_date, n_train_matches,
                          n_test_matches, n_bets
                   FROM backtest_run_windows
                   WHERE run_id = %s
                   ORDER BY window_index""",
                (run_id,),
            )
            wcols = [desc[0] for desc in cur.description]
            windows = []
            for wrow in cur.fetchall():
                w = dict(zip(wcols, wrow, strict=False))
                for k in w:
                    if hasattr(w[k], "isoformat"):
                        w[k] = str(w[k])
                windows.append(w)

            # Results — aggregate (window_index IS NULL) first, then per-window
            cur.execute(
                """SELECT window_index, model_name,
                          n_bets, n_wins, hit_rate, roi, total_profit, avg_odds,
                          brier_score, log_loss, clv,
                          max_drawdown, max_drawdown_pct, longest_losing_streak,
                          sharpe_ratio, profit_factor, equity_curve
                   FROM backtest_run_results
                   WHERE run_id = %s
                   ORDER BY window_index NULLS FIRST, model_name""",
                (run_id,),
            )
            rcols = [desc[0] for desc in cur.description]
            results = []
            for rrow in cur.fetchall():
                r = dict(zip(rcols, rrow, strict=False))
                for k in r:
                    if hasattr(r[k], "isoformat"):
                        r[k] = str(r[k])
                results.append(r)

    return {
        "run": run,
        "windows": windows,
        "results": results,
    }


@router.get("/api/backtests/{run_id}/equity-curve")
def get_backtest_equity_curve(
    run_id: int,
    model_name: str | None = Query(None),
):
    """Get equity curve data for a backtest run (optionally filtered by model)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if model_name:
                cur.execute(
                    """SELECT model_name, equity_curve
                       FROM backtest_run_results
                       WHERE run_id = %s AND window_index IS NULL AND model_name = %s""",
                    (run_id, model_name),
                )
            else:
                cur.execute(
                    """SELECT model_name, equity_curve
                       FROM backtest_run_results
                       WHERE run_id = %s AND window_index IS NULL
                       ORDER BY model_name""",
                    (run_id,),
                )
            rows = cur.fetchall()

    curves = {}
    for row in rows:
        curves[row[0]] = row[1] if row[1] else []

    return {
        "run_id": run_id,
        "model_name": model_name,
        "curves": curves,
    }


@router.post("/api/backtests")
def create_backtest(body: dict):
    """Create and run a new backtest.

    Request body:
        {
            "name": str (optional),
            "model_names": [str] (optional, default = all active),
            "time_start": "YYYY-MM-DD" (optional),
            "time_end": "YYYY-MM-DD" (optional),
            "league_ids": [int] (optional),
            "odds_min": float (optional),
            "odds_max": float (optional),
            "ev_min": float (optional),
            "min_model_prob": float (optional, default 0.35),
            "signal_strength": "strong" | "weak" | "all" (optional),
            "walk_forward": bool (optional, default true),
            "dry_run": bool (optional, default false)
        }
    """
    model_names = body.get("model_names")
    dry_run = body.get("dry_run", False)

    if dry_run:
        return {"status": "dry_run", "message": "backtest creation acknowledged (dry run)"}

    # If no model names specified, use all active
    if not model_names:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT model_name FROM model_versions WHERE is_active = true")
                model_names = [row[0] for row in cur.fetchall()]

    if not model_names:
        return {"status": "error", "error": "no models to test"}

    today = business_today()
    name = body.get("name") or f"手动回测-{today.isoformat()}"

    config = BacktestConfig(
        name=name,
        description=body.get("description", ""),
        time_start=body.get("time_start"),
        time_end=body.get("time_end"),
        league_ids=body.get("league_ids"),
        play_types=body.get("play_types", ["spf"]),
        odds_min=body.get("odds_min"),
        odds_max=body.get("odds_max"),
        ev_min=body.get("ev_min"),
        model_names=model_names,
        confidence_min=body.get("confidence_min"),
        vote_directions=body.get("vote_directions"),
        walk_forward=body.get("walk_forward", True),
        train_window_days=body.get("train_window_days", 365),
        test_window_days=body.get("test_window_days", 90),
        step_days=body.get("step_days", 90),
        stake_per_bet=body.get("stake_per_bet", 1.0),
        min_model_prob=body.get("min_model_prob", 0.35),
        signal_strength=body.get("signal_strength", "strong"),
    )

    with get_db() as conn:
        result = run_backtest_from_config(conn, config, store=True)

    # Build simplified response
    aggregate_summary = {}
    for m, metrics in result.get("aggregate", {}).items():
        aggregate_summary[m] = {k: v for k, v in metrics.items() if k != "equity_curve"}

    return {
        "status": result.get("status", "ok"),
        "run_id": result.get("run_id"),
        "config": config.to_dict(),
        "total_bets": result.get("total_bets", 0),
        "total_windows": result.get("total_windows", 0),
        "aggregate": aggregate_summary,
    }
