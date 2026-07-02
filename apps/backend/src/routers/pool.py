"""传统足彩 14场/任九 API 端点 (Phase 10)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from apps.backend.src.db import get_db
from scripts.pool_combination_optimizer import (
    PoolMatch,
    analyze_pool,
    pool_analysis_to_dict,
)

router = APIRouter(tags=["pool"])


@router.get("/api/pool/analyze")
def run_pool_analysis(
    budget: int = Query(256, description="预算（元）"),
    strategy: str = Query("balanced", description="策略：conservative | balanced | aggressive"),
    seed_match_id: Optional[int] = Query(  # noqa: UP045
        None, description="指定基准比赛ID（可选，用于筛选同期比赛）"
    ),
):
    """对14场比赛运行完整的传统足彩分析。

    从模型预测中选取14场比赛（按预测时间最新），运行：
    1. 冷门指数计算
    2. 胆/拖/防守分类
    3. 胆拖组合优化
    4. 蒙特卡洛模拟（命中14/13/任九概率）
    5. 任九选项

    返回完整分析报告。
    """
    if strategy not in ("conservative", "balanced", "aggressive"):
        raise HTTPException(400, "strategy must be conservative | balanced | aggressive")

    with get_db() as conn:
        with conn.cursor() as cur:
            # 获取14场最新的模型预测（每场取最新的预测）
            cur.execute(
                """
                SELECT DISTINCT ON (mp.match_id)
                    mp.match_id,
                    m.home_team_name AS home_team,
                    m.away_team_name AS away_team,
                    m.league_name AS league,
                    m.match_date::text AS match_date,
                    mv.model_name
                FROM model_predictions mp
                JOIN official_matches m ON m.id = mp.match_id
                JOIN model_versions mv ON mv.id = mp.model_version_id
                ORDER BY mp.match_id, mp.predict_time DESC
                LIMIT 14
                """
            )
            matches = cur.fetchall()

            if len(matches) < 14:
                raise HTTPException(
                    400,
                    f"当前只有 {len(matches)} 场比赛有模型预测，需要至少14场才能进行传统足彩分析",
                )

            # 对每场比赛获取完整的3/1/0概率
            pool_matches = []
            for row in matches:
                match_id = row[0]
                cur.execute(
                    """
                    SELECT option_code, model_probability
                    FROM model_predictions
                    WHERE match_id = %s AND play_type = 'spf'
                    ORDER BY predict_time DESC
                    LIMIT 3
                    """,
                    (match_id,),
                )
                probs = {r[0]: float(r[1] or 0) for r in cur.fetchall()}

                pool_match = PoolMatch(
                    match_id=match_id,
                    home_team=row[1],
                    away_team=row[2],
                    league=row[3] or "",
                    match_date=str(row[4]) if row[4] else "",
                    prob_home=probs.get("3", 0.33),
                    prob_draw=probs.get("1", 0.34),
                    prob_away=probs.get("0", 0.33),
                    data_quality=0.7,  # default, could be from feature snapshot
                )
                pool_matches.append(pool_match)

    # 运行分析
    analysis = analyze_pool(
        pool_matches,
        budget=budget,
        strategy=strategy,
        period_id=f"pool-{pool_matches[0].match_date}"
        if pool_matches[0].match_date
        else "pool-auto",
    )

    return pool_analysis_to_dict(analysis)


@router.get("/api/pool/sample")
def get_pool_sample():
    """生成示例14场比赛数据并返回分析结果（用于前端演示/测试）。

    使用合成数据，不访问数据库。
    """
    import random

    rng = random.Random(42)

    sample_teams = [
        ("曼联", "利物浦", "英超"),
        ("阿森纳", "切尔西", "英超"),
        ("曼城", "热刺", "英超"),
        ("纽卡斯尔", "阿斯顿维拉", "英超"),
        ("布莱顿", "狼队", "英超"),
        ("富勒姆", "伯恩茅斯", "英超"),
        ("巴萨", "皇马", "西甲"),
        ("马竞", "塞维利亚", "西甲"),
        ("瓦伦西亚", "比利亚雷亚尔", "西甲"),
        ("国际米兰", "AC米兰", "意甲"),
        ("尤文图斯", "罗马", "意甲"),
        ("那不勒斯", "拉齐奥", "意甲"),
        ("拜仁", "多特蒙德", "德甲"),
        ("莱比锡", "勒沃库森", "德甲"),
    ]

    matches = []
    for i, (home, away, league) in enumerate(sample_teams):
        # 生成合理的概率
        p_home = rng.uniform(0.25, 0.55)
        p_draw = rng.uniform(0.18, 0.35)
        p_away = 1.0 - p_home - p_draw

        is_derby = i in (0, 9)  # 曼联vs利物浦, 国米vs米兰
        is_top = i in (2, 6)  # 曼城vs热刺, 巴萨vs皇马

        m = PoolMatch(
            match_id=i + 1,
            home_team=home,
            away_team=away,
            league=league,
            match_date="2026-07-03",
            prob_home=round(p_home, 4),
            prob_draw=round(p_draw, 4),
            prob_away=round(p_away, 4),
            market_odds_home=round(1.0 / p_home * 0.92, 2) if p_home > 0 else None,
            market_odds_draw=round(1.0 / p_draw * 0.92, 2) if p_draw > 0 else None,
            market_odds_away=round(1.0 / p_away * 0.92, 2) if p_away > 0 else None,
            uncertainty=round(rng.uniform(0.2, 0.7), 4),
            data_quality=round(rng.uniform(0.5, 1.0), 4),
            is_derby=is_derby,
            is_top_clash=is_top,
        )
        matches.append(m)

    analysis = analyze_pool(
        matches,
        budget=256,
        strategy="balanced",
        period_id="sample-2026-07-03",
    )

    return pool_analysis_to_dict(analysis)
