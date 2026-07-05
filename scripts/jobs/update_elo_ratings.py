"""Elo 评分更新任务。

赛后批量更新球队 Elo 评分：
  1. 查询已结算但未处理 Elo 的比赛
  2. 检查 elo_update_logs 避免重复处理
  3. 按比赛时间排序，顺序更新（保证 Elo 流转正确）
  4. 写入 elo_update_logs 并更新 team_elo_ratings
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.elo_model import update_elo_ratings


def run(dry_run: bool = False) -> dict[str, Any]:
    """处理所有已结算但尚未更新 Elo 的比赛。"""
    if dry_run:
        return {"status": "dry_run", "message": "elo update (dry run)"}

    with get_db() as conn:
        # 查询需要处理的结果：
        # - official_results 中有比分
        # - official_matches 已结算
        # - elo_update_logs 中无记录
        cur = conn.cursor()
        cur.execute("""
            SELECT
                m.id AS match_id,
                COALESCE(t1.id, 0) AS home_team_id,
                COALESCE(t2.id, 0) AS away_team_id,
                DATE(m.kickoff_time)::text AS match_date,
                r.full_home_goals AS home_goals,
                r.full_away_goals AS away_goals,
                COALESCE(t1.team_name_cn, m.home_team_name) AS home_name,
                COALESCE(t2.team_name_cn, m.away_team_name) AS away_name,
                m.league_name AS season,
                NULL AS league_tier
            FROM official_matches m
            JOIN official_results r ON r.match_id = m.id
            LEFT JOIN teams t1 ON t1.team_name_cn = m.home_team_name
            LEFT JOIN teams t2 ON t2.team_name_cn = m.away_team_name
            LEFT JOIN elo_update_logs el ON el.match_id = m.id
            WHERE r.full_home_goals IS NOT NULL
              AND r.full_away_goals IS NOT NULL
              AND m.match_status = 'Settled'
              AND el.id IS NULL
            ORDER BY m.kickoff_time ASC, m.id ASC
        """)
        matches = cur.fetchall()

        if not matches:
            return {"status": "ok", "updated": 0, "note": "no new settled matches"}

        updated = 0
        errors = 0

        for row in matches:
            (
                match_id,
                home_team_id,
                away_team_id,
                match_date,
                home_goals,
                away_goals,
                home_name,
                away_name,
                season,
                league_tier,
            ) = row

            try:
                update_elo_ratings(
                    conn,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    home_goals=int(home_goals),
                    away_goals=int(away_goals),
                    match_id=int(match_id),
                    match_date=match_date,
                    season=season,
                    league_tier=league_tier,
                )
                updated += 1
            except Exception as exc:
                errors += 1
                print(f"[elo] ERROR match_id={match_id}: {exc}", flush=True)

        return {
            "status": "ok",
            "updated": updated,
            "errors": errors,
            "total_matches_processed": len(matches),
        }
