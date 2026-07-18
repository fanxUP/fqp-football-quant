"""传统足彩 14场/任九 API 端点 (Phase 10)."""

from __future__ import annotations

from functools import lru_cache
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
    issue_id: Optional[str] = Query(  # noqa: UP045
        None, description="指定官方期号或本地期次ID"
    ),
):
    """对体彩官方当前胜负彩14场运行完整分析。

    只从已采集的官方彩池期号读取比赛，再关联本地模型预测。禁止把
    竞彩足球在售比赛拼成传统足彩14场。

    运行：
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
            # 官方胜负彩彩池是唯一的14场来源。
            cur.execute(
                """
                SELECT i.id, i.issue_no, i.game_type, i.total_matches,
                       i.official_status, i.sale_stop_time::text,
                       im.match_order, im.match_id,
                       COALESCE(im.home_team_name, m.home_team_name) AS home_team,
                       COALESCE(im.away_team_name, m.away_team_name) AS away_team,
                       COALESCE(im.league_name, m.league_name) AS league,
                       COALESCE(im.kickoff_time, m.kickoff_time)::text AS match_date,
                       m.id AS official_match_id,
                       latest.model_name,
                       latest.prob_home, latest.prob_draw, latest.prob_away
                FROM football_pool_issues i
                JOIN football_pool_issue_matches im ON im.issue_id = i.id
                LEFT JOIN official_matches m
                  ON m.id = im.match_id
                  OR (m.home_team_name = im.home_team_name
                      AND m.away_team_name = im.away_team_name
                      AND m.kickoff_time::date = im.kickoff_time::date)
                LEFT JOIN LATERAL (
                    WITH latest_model_options AS (
                        SELECT DISTINCT ON (mp.model_version_id, mp.option_code)
                               mp.model_version_id, mp.option_code, mp.model_probability
                        FROM model_predictions mp
                        JOIN model_versions mv ON mv.id = mp.model_version_id
                        WHERE mp.match_id = m.id
                          AND mp.play_type = 'spf'
                          AND mp.predict_time < m.kickoff_time
                          AND mv.is_active = true
                          AND mp.model_probability IS NOT NULL
                        ORDER BY mp.model_version_id, mp.option_code,
                                 mp.predict_time DESC, mp.id DESC
                    )
                    SELECT '模型共识' AS model_name,
                           AVG(model_probability) FILTER (WHERE option_code = '3') AS prob_home,
                           AVG(model_probability) FILTER (WHERE option_code = '1') AS prob_draw,
                           AVG(model_probability) FILTER (WHERE option_code = '0') AS prob_away
                    FROM latest_model_options
                    HAVING COUNT(DISTINCT model_version_id) > 0
                ) latest ON true
                WHERE i.game_type = 't14c'
                  AND (%s IS NULL OR i.id::text = %s OR i.issue_no = %s)
                ORDER BY CASE WHEN i.official_status = 'selling' THEN 0 ELSE 1 END,
                         i.sale_stop_time DESC NULLS LAST, i.updated_at DESC,
                         im.match_order
                """,
                (issue_id, issue_id, issue_id),
            )
            rows = cur.fetchall()

            if not rows:
                raise HTTPException(404, "暂无已采集的体彩官方14场彩池")

            issues: dict[int, list[tuple]] = {}
            for row in rows:
                issues.setdefault(int(row[0]), []).append(row)

            def ready_count(issue_rows: list[tuple]) -> int:
                return sum(
                    row[12] is not None and all(row[idx] is not None for idx in (14, 15, 16))
                    for row in issue_rows
                )

            ordered_issues = list(issues.values())
            first_issue = ordered_issues[0]
            first_is_current = first_issue[0][4] == "selling"
            if first_is_current or issue_id is not None:
                matches = first_issue
            else:
                matches = next(
                    (
                        issue_rows
                        for issue_rows in ordered_issues
                        if issue_rows[0][3] == 14
                        and len(issue_rows) == 14
                        and ready_count(issue_rows) == 14
                    ),
                    first_issue,
                )

            issue_no = matches[0][1]
            if matches[0][3] != 14 or len(matches) != 14:
                raise HTTPException(
                    409,
                    f"官方14场彩池数据不完整：期号 {issue_no}，应为14场，当前 {len(matches)}场",
                )
            predicted_count = ready_count(matches)
            if predicted_count < 14:
                raise HTTPException(
                    409,
                    f"期号 {issue_no} 已完成 {predicted_count}/14 场模型预测，待补齐 {14 - predicted_count} 场后生成组合",
                )

            if len(matches) < 14:
                raise HTTPException(
                    400,
                    f"当前只有 {len(matches)} 场官方比赛，需要14场",
                )

            # 对每场官方比赛使用各活跃模型最新赛前概率的共识均值。
            pool_matches = []
            for row in matches:
                pool_match = PoolMatch(
                    match_id=row[12] or row[7] or row[6],
                    home_team=row[8],
                    away_team=row[9],
                    league=row[10] or "",
                    match_date=str(row[11]) if row[11] else "",
                    prob_home=float(row[14] or 0),
                    prob_draw=float(row[15] or 0),
                    prob_away=float(row[16] or 0),
                    data_quality=1.0,
                )
                pool_matches.append(pool_match)

    # 运行分析
    analysis = analyze_pool(
        pool_matches,
        budget=budget,
        strategy=strategy,
        period_id=f"{issue_no}-t14c",
    )

    result = pool_analysis_to_dict(analysis)
    issue_status = str(matches[0][4] or "unknown")
    result["analysis_mode"] = "current" if issue_status == "selling" else "historical"
    result["issue"] = {
        "id": matches[0][0],
        "issue_no": issue_no,
        "status": issue_status,
        "sale_stop": matches[0][5],
        "source": "sporttery",
    }
    return result


@lru_cache(maxsize=1)
def _build_pool_sample() -> dict:
    """Build the deterministic demonstration pool once per process."""
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
        n_mc_simulations=1_000,
        period_id="sample-2026-07-03",
    )

    return pool_analysis_to_dict(analysis)


@router.get("/api/pool/sample")
def get_pool_sample():
    """返回固定种子的14场演示分析结果；使用合成数据，不访问数据库。"""
    return _build_pool_sample()


@router.get("/api/pool/issues")
def list_pool_issues():
    """List real official pool issues stored by the Sporttery collector."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.id, i.issue_no, i.game_type, i.official_status,
                       i.total_matches, i.sale_start_time, i.sale_stop_time,
                       COUNT(im.id) AS stored_matches
                FROM football_pool_issues i
                LEFT JOIN football_pool_issue_matches im ON im.issue_id = i.id
                GROUP BY i.id
                ORDER BY i.sale_stop_time DESC NULLS LAST, i.updated_at DESC
                """
            )
            rows = cur.fetchall()

    issues = [
        {
            "id": row[0],
            "issue_no": row[1],
            "game_type": row[2],
            "status": row[3],
            "total_matches": row[4],
            "stored_matches": row[7],
            "sale_start": row[5].isoformat() if row[5] else None,
            "sale_stop": row[6].isoformat() if row[6] else None,
            "source": "sporttery",
        }
        for row in rows
    ]
    return {"issues": issues, "total": len(issues)}


@router.post("/api/pool/issues/{issue_id}/generate-combinations")
def generate_pool_issue_combinations(
    issue_id: str,
    budget: int = Query(256, description="预算（元）"),
    strategy: str = Query("balanced", description="策略：conservative | balanced | aggressive"),
):
    """Compatibility wrapper around the current pool analyzer."""
    result = run_pool_analysis(
        budget=budget,
        strategy=strategy,
        seed_match_id=None,
        issue_id=issue_id,
    )
    result["issue_id"] = issue_id
    return result
