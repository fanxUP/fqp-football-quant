"""FQP Dashboard API — aggregated data views for data visualization.

All endpoints read from v_dashboard_* views and return structured chart-ready payloads.
Empty data → {"empty": true, "empty_reason": "..."}  (never 500).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from apps.backend.src.db import get_db
from apps.backend.src.services.odds_movement import list_odds_movements
from scripts.business_time import business_now

router = APIRouter(tags=["dashboard"])


def _meta(source: str) -> dict:
    return {
        "updated_at": business_now().isoformat(timespec="seconds"),
        "source": source,
    }


def _empty(title: str, reason: str = "暂无数据") -> dict:
    return {
        "chart_type": "empty",
        "title": title,
        "empty": True,
        "empty_reason": reason,
        "series": [],
        "meta": _meta("view"),
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/today — KPI summary for homepage
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/today")
def get_today_summary():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM v_dashboard_today_summary")
                row = cur.fetchone()
    except Exception:
        return _empty(
            "今日总览", "无法读取 Dashboard 视图，请确认 v_dashboard_today_summary 已创建"
        )

    if not row:
        return _empty("今日总览", "暂无今日数据")

    columns = [desc[0] for desc in cur.description]
    data = dict(zip(columns, row, strict=False))
    return {
        "code": 0,
        "data": {
            "chart_type": "kpi",
            "title": "今日总览",
            "empty": False,
            "kpis": [
                {
                    "key": "match_count",
                    "label": "在售比赛",
                    "value": data.get("match_count", 0),
                },
                {
                    "key": "predicted_match_count",
                    "label": "已预测比赛",
                    "value": data.get("predicted_match_count", 0),
                },
                {
                    "key": "ai_stake_today",
                    "label": "AI 模拟投入",
                    "value": float(data.get("ai_stake_today", 0)),
                    "prefix": "¥",
                },
                {
                    "key": "ai_ticket_count",
                    "label": "AI 票单数",
                    "value": data.get("ai_ticket_count", 0),
                },
                {
                    "key": "pending_settlement_count",
                    "label": "待开奖",
                    "value": data.get("pending_settlement_count", 0),
                },
                {
                    "key": "ai_settled_stake_today",
                    "label": "AI 当日结算本金",
                    "value": float(data.get("ai_settled_stake_today", 0)),
                    "prefix": "¥",
                },
                {
                    "key": "ai_today_profit_loss",
                    "label": "AI 当日盈亏",
                    "value": float(data.get("ai_today_profit_loss", 0)),
                    "prefix": "¥",
                },
                {
                    "key": "real_today_profit_loss",
                    "label": "实盘当日盈亏",
                    "value": float(data.get("real_today_profit_loss", 0)),
                    "prefix": "¥",
                },
            ],
            "meta": _meta("v_dashboard_today_summary"),
            "extras": {
                "current_round_label": data.get("current_round_label"),
                "current_round_id": data.get("current_round_id"),
                "business_date": str(data.get("business_date", "")),
            },
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/roi/daily — daily ROI comparison
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/roi/daily")
def get_roi_daily(
    days: int = Query(30, ge=1, le=180, description="历史天数"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM v_dashboard_roi_daily
                       WHERE snapshot_date >= CURRENT_DATE - %s::int
                       ORDER BY snapshot_date""",
                    (days,),
                )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("每日 ROI 对比", "无法读取 ROI 视图")

    if not rows:
        return _empty("每日 ROI 对比", f"近 {days} 天无 ROI 数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "mixed",
            "title": "每日 ROI 对比",
            "empty": False,
            "series": series,
            "meta": _meta("v_dashboard_roi_daily"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/roi/period — round-level ROI summaries
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/roi/period")
def get_roi_period(
    limit: int = Query(12, ge=1, le=52, description="返回期数"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM v_dashboard_roi_period
                       ORDER BY round_start DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("周期 ROI 汇总", "无法读取周期 ROI 视图")

    if not rows:
        return _empty("周期 ROI 汇总", "暂无周期比赛数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "mixed",
            "title": "周期 ROI 汇总",
            "empty": False,
            "series": series,
            "meta": _meta("v_dashboard_roi_period"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/recommendations — prediction-based recommendations
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/recommendations")
def get_recommendations(
    match_id: int | None = Query(None, description="按比赛筛选"),
    limit: int = Query(30, ge=1, le=200),
    min_ev: float = Query(0.0, description="最小 EV 阈值"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if match_id:
                    cur.execute(
                        """SELECT * FROM v_dashboard_recommendation_summary
                           WHERE match_id = %s AND ev >= %s
                           ORDER BY ev DESC LIMIT %s""",
                        (match_id, min_ev, limit),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM v_dashboard_recommendation_summary
                           WHERE ev >= %s
                           ORDER BY ev DESC LIMIT %s""",
                        (min_ev, limit),
                    )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("推荐概览", "无法读取推荐视图")

    if not rows:
        return _empty("推荐概览", min_ev > 0 and "暂无满足 EV 阈值的推荐" or "暂无推荐数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "table",
            "title": "推荐概览",
            "empty": False,
            "series": series,
            "meta": _meta("v_dashboard_recommendation_summary"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/odds/movement — SP time series
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/odds/movement")
def get_odds_movement(
    match_id: int = Query(..., description="比赛 ID"),
    play_type: str = Query("spf", description="玩法代码"),
    option_code: str | None = Query(None, description="选项代码（可选，如 h/d/a）"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if option_code:
                    cur.execute(
                        """SELECT * FROM v_dashboard_odds_movement
                           WHERE match_id = %s AND play_type = %s AND option_code = %s
                           ORDER BY snapshot_time""",
                        (match_id, play_type, option_code),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM v_dashboard_odds_movement
                           WHERE match_id = %s AND play_type = %s
                           ORDER BY snapshot_time""",
                        (match_id, play_type),
                    )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("赔率走势", "无法读取赔率视图")

    if not rows:
        return _empty("赔率走势", "该比赛暂无赔率快照数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    # Build anomalies list
    anomalies: list[dict] = []
    for r in series:
        prev = r.get("prev_sp_value")
        curr = r.get("sp_value")
        if prev and curr and curr > 0 and prev > 0:
            ratio = curr / prev
            if ratio > 3 or ratio < 0.33:
                anomalies.append(
                    {
                        "time": str(r.get("snapshot_time", "")),
                        "option_name": r.get("option_name"),
                        "sp_value": float(curr),
                        "prev_sp_value": float(prev),
                        "ratio": round(ratio, 2),
                        "type": "jump" if ratio > 1 else "drop",
                    }
                )

    return {
        "code": 0,
        "data": {
            "chart_type": "line",
            "title": "赔率走势",
            "empty": False,
            "series": series,
            "anomalies": anomalies,
            "meta": _meta("v_dashboard_odds_movement"),
        },
    }


@router.get("/api/dashboard/odds/movements")
def get_odds_movements(
    scope: Literal["current", "history"] = Query("current"),
    business_date: str | None = Query(None),
    play_type: Literal["spf", "rqspf", "bf", "zjq", "bqc"] = Query("spf"),
    resolution: Literal["raw", "hour"] = Query("raw"),
    limit: int = Query(200, ge=1, le=200),
):
    """Return all date-scoped matches and their selected-play odds in one request."""
    if scope == "history" and not business_date:
        raise HTTPException(status_code=422, detail="历史走势必须指定 business_date")
    if business_date:
        try:
            date.fromisoformat(business_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="business_date 格式必须为 YYYY-MM-DD"
            ) from exc
    return list_odds_movements(
        scope=scope,
        business_date=business_date,
        play_type=play_type,
        resolution=resolution,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/model-performance — model evaluation summary
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/model-performance")
def get_model_performance(
    model_name: str | None = Query(None, description="模型名称（可选）"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if model_name:
                    cur.execute(
                        """SELECT * FROM v_dashboard_model_performance
                           WHERE model_name = %s
                           ORDER BY version DESC LIMIT 10""",
                        (model_name,),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM v_dashboard_model_performance
                           ORDER BY model_name, version DESC"""
                    )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("模型表现", "无法读取模型表现视图")

    if not rows:
        return _empty("模型表现", "暂无模型评估数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "mixed",
            "title": "模型表现",
            "empty": False,
            "series": series,
            "meta": _meta("v_dashboard_model_performance"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/backtest/equity — backtest equity curves
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/backtest/equity")
def get_backtest_equity(
    run_id: int = Query(..., description="回测运行 ID"),
    model_name: str | None = Query(None, description="模型名称（可选）"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if model_name:
                    cur.execute(
                        """SELECT * FROM v_dashboard_backtest_equity
                           WHERE run_id = %s AND model_name = %s
                           ORDER BY window_index""",
                        (run_id, model_name),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM v_dashboard_backtest_equity
                           WHERE run_id = %s
                           ORDER BY window_index""",
                        (run_id,),
                    )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("回测资金曲线", "无法读取回测视图")

    if not rows:
        return _empty("回测资金曲线", "该回测运行暂无数据")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "mixed",
            "title": "回测资金曲线",
            "empty": False,
            "series": series,
            "meta": _meta("v_dashboard_backtest_equity"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/ticket-review — daily settlement overview
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/ticket-review")
def get_ticket_review(
    days: int = Query(30, ge=1, le=90, description="回顾天数"),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date AS settle_date,
                        ts.ticket_source,
                        COUNT(*) AS ticket_count,
                        SUM(CASE WHEN ts.is_won THEN 1 ELSE 0 END) AS won_count,
                        SUM(ts.stake_amount) AS total_stake,
                        SUM(ts.net_prize) AS total_prize,
                        SUM(ts.profit_loss) AS total_profit_loss,
                        CASE WHEN SUM(ts.stake_amount) > 0
                             THEN SUM(ts.profit_loss) / NULLIF(SUM(ts.stake_amount), 0)
                             ELSE NULL END AS roi
                    FROM ticket_settlements ts
                    WHERE (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                          >= timezone('Asia/Shanghai', NOW())::date - %s::int
                    GROUP BY (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date,
                             ts.ticket_source
                    ORDER BY settle_date DESC""",
                    (days,),
                )
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
    except Exception:
        return _empty("票单复盘", "无法读取结算数据")

    if not rows:
        return _empty("票单复盘", f"近 {days} 天无结算记录")

    series = [dict(zip(columns, r, strict=False)) for r in rows]
    return {
        "code": 0,
        "data": {
            "chart_type": "mixed",
            "title": "票单复盘",
            "empty": False,
            "series": series,
            "meta": _meta("ticket_settlements"),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/panels — panel layout configuration
# ---------------------------------------------------------------------------
@router.get("/api/dashboard/panels")
def get_panels_config():
    return {
        "code": 0,
        "data": {
            "chart_type": "config",
            "title": "面板配置",
            "empty": False,
            "panels": [
                {"id": "today_kpi", "name": "KPI 总览", "route": "/", "order": 1},
                {"id": "roi_competition", "name": "ROI 对战", "route": "/competition", "order": 2},
                {
                    "id": "recommendations",
                    "name": "推荐概览",
                    "route": "/recommendations",
                    "order": 3,
                },
                {"id": "odds_movement", "name": "赔率走势", "route": "/odds", "order": 4},
                {"id": "model_perf", "name": "模型表现", "route": "/models", "order": 5},
                {"id": "backtest", "name": "回测分析", "route": "/backtest", "order": 6},
                {"id": "ticket_review", "name": "票单复盘", "route": "/reviews", "order": 7},
            ],
            "meta": _meta("config"),
        },
    }
