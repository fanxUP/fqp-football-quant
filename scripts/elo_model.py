"""Elo 动态评级模型。

基于 Elo 评分系统 (Elo, 1978) 计算球队动态实力评分。

核心公式:
  E_A = 1 / (1 + 10^((R_B - R_A) / 400))   ← A 对 B 的预期得分率
  R_A' = R_A + K * G * (S_A - E_A)           ← 赛后更新

其中:
  R_A, R_B = 赛前 Elo 评分
  K        = 基础 K 因子（默认 32）
  G        = 进球差系数 = sqrt(|goal_diff|) if goal_diff > 1 else 1
  S_A      = 实际结果: 1 (胜), 0.5 (平), 0 (负)

足球特定调整:
  - 主场优势: +100 Elo 点（约 64% 的预期胜率）
  - 进球差系数: 大胜/惨败的 K 值更高
  - 联赛差异化 K: 顶级联赛 K=32, 次级 K=24
  - Elo 分转化为 1x2 概率（用于模型委员会投票）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Forward reference for DB connection (Any to avoid circular imports)
# conn provides: .cursor() → cursor, .commit()

# —— 常量 ——
DEFAULT_K = 32  # 基础 K 因子
HOME_ADVANTAGE = 100  # 主场优势 (Elo 分)
INITIAL_ELO = 1500  # 新球队初始 Elo
ELO_SCALE = 400  # Elo 缩放因子
DRAW_WIDTH = 0.25  # 平局宽度参数（Elo 差→平局概率）


# —— 数据结构 ——


@dataclass
class EloRating:
    """单条 Elo 评分记录。"""

    team_id: int
    team_name: str
    elo_rating: float
    matches_played: int
    season: str | None
    last_match_date: str | None
    peak_elo: float  # 历史峰值
    home_win_pct: float  # 主场胜率
    away_win_pct: float  # 客场胜率
    updated_at: str


# —— 核心计算 ——


def expected_score(rating_a: float, rating_b: float) -> float:
    """球队 A 对 B 的 Elo 预期得分率 E_A ∈ [0, 1]。

    E_A = 1 / (1 + 10^((R_B - R_A) / 400))
    """
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / ELO_SCALE))


def expected_score_with_home(rating_home: float, rating_away: float) -> float:
    """主场球队的预期得分率（含主场优势）。"""
    return expected_score(rating_home + HOME_ADVANTAGE, rating_away)


def update_elo(
    rating: float,
    opponent_rating: float,
    result: float,
    goal_diff: int = 0,
    k_factor: float = DEFAULT_K,
    is_home: bool = True,
) -> float:
    """单场比赛后更新 Elo 评分。

    Args:
        rating: 当前 Elo 分
        opponent_rating: 对手 Elo 分
        result: 1.0 (胜), 0.5 (平), 0.0 (负)
        goal_diff: 净胜球差（绝对值）
        k_factor: K 因子
        is_home: 是否主场

    Returns:
        新 Elo 评分
    """
    # 调整对手评分（主场优势）
    if is_home:
        expected = expected_score(rating + HOME_ADVANTAGE, opponent_rating)
    else:
        expected = expected_score(rating, opponent_rating + HOME_ADVANTAGE)

    # 进球差加权
    g_factor = 1.0
    if goal_diff > 1:
        g_factor = math.sqrt(float(goal_diff))
    elif goal_diff < -1:
        g_factor = math.sqrt(float(abs(goal_diff)))

    delta = k_factor * g_factor * (result - expected)
    return rating + delta


def elo_to_1x2(home_elo: float, away_elo: float) -> dict[str, float]:
    """将 Elo 评分差转化为胜/平/负概率。

    使用 logistic 类模型：
      - 首先计算主场预期得分率 E_home
      - 平局概率 = f(E_home)  集中在 50% 附近
      - 主胜概率 = E_home - draw_prob / 2
      - 客胜概率 = 1 - E_home - draw_prob / 2

    Args:
        home_elo: 主场球队 Elo
        away_elo: 客场球队 Elo

    Returns:
        {"3": P_home_win, "1": P_draw, "0": P_away_win}
    """
    e_home = expected_score(home_elo + HOME_ADVANTAGE, away_elo)

    # 平局概率：E_home 越接近 0.5，平局概率越高
    # 使用 truncated normal / logistic approach
    gap = abs(e_home - 0.5)
    draw_p = 0.30 * math.exp(-gap * gap / (2.0 * DRAW_WIDTH * DRAW_WIDTH))

    # 边界处理
    draw_p = max(0.08, min(0.38, draw_p))

    home_p = e_home - draw_p / 2.0
    away_p = 1.0 - e_home - draw_p / 2.0

    # 归一化 & clamp
    home_p = max(0.01, min(0.95, home_p))
    away_p = max(0.01, min(0.95, away_p))
    draw_p = max(0.01, min(0.50, draw_p))

    total = home_p + draw_p + away_p
    return {"3": home_p / total, "1": draw_p / total, "0": away_p / total}


def league_k_factor(league_tier: str | None) -> float:
    """根据联赛级别返回 K 因子。

    Args:
        league_tier: "top5", "second", "other", None

    Returns:
        K 因子
    """
    tiers = {
        "top5": 32,  # 英超/西甲/德甲/意甲/法甲
        "second": 24,  # 荷甲/葡超/巴甲等
        "other": 20,
    }
    return tiers.get(league_tier or "other", DEFAULT_K)


def initial_elo_for_team(league_tier: str | None) -> float:
    """为新球队分配初始 Elo 评分。

    Args:
        league_tier: 联赛级别

    Returns:
        初始 Elo 评分
    """
    base = {
        "top5": 1500,
        "second": 1400,
        "other": 1300,
    }
    return base.get(league_tier or "other", INITIAL_ELO)


# —— 批量更新 ——


def process_match_results(
    home_elo: float,
    away_elo: float,
    home_goals: int,
    away_goals: int,
    league_tier: str | None = None,
) -> tuple[float, float]:
    """处理单场比赛结果，返回 (new_home_elo, new_away_elo)。

    Args:
        home_elo: 主队赛前 Elo
        away_elo: 客队赛前 Elo
        home_goals: 主队进球
        away_goals: 客队进球
        league_tier: 联赛级别

    Returns:
        (new_home_elo, new_away_elo)
    """
    k = league_k_factor(league_tier)

    if home_goals > away_goals:
        home_result, away_result = 1.0, 0.0
    elif home_goals == away_goals:
        home_result, away_result = 0.5, 0.5
    else:
        home_result, away_result = 0.0, 1.0

    goal_diff = home_goals - away_goals

    new_home = update_elo(
        home_elo,
        away_elo,
        home_result,
        goal_diff=goal_diff,
        k_factor=k,
        is_home=True,
    )
    new_away = update_elo(
        away_elo,
        home_elo,
        away_result,
        goal_diff=-goal_diff,
        k_factor=k,
        is_home=False,
    )

    return (round(new_home, 2), round(new_away, 2))


def run_elo_1x2_prediction(
    home_elo: float,
    away_elo: float,
) -> dict[str, float]:
    """基于 Elo 评分的 1x2 预测（用于模型委员会）。

    与 Poisson/Dixon-Coles 不同，Elo 模型直接依赖历史比赛结果，
    不受赔率数据质量影响。适合作为委员会中的"纯实力"投票元。

    Args:
        home_elo: 主队 Elo
        away_elo: 客队 Elo

    Returns:
        {"3": P_home, "1": P_draw, "0": P_away}
    """
    return elo_to_1x2(home_elo, away_elo)


# —— 存储层 ——


def get_team_elo(conn: Any, team_id: int, season: str | None = None) -> float:
    """获取球队当前 Elo 评分。

    Args:
        conn: DB 连接
        team_id: 球队 ID
        season: 赛季（None = 最近赛季）

    Returns:
        Elo 评分，默认 1500
    """
    if season:
        cur = conn.cursor()
        cur.execute(
            "SELECT elo_rating FROM team_elo_ratings WHERE team_id = %s AND season = %s",
            (team_id, season),
        )
    else:
        cur = conn.cursor()
        cur.execute(
            "SELECT elo_rating FROM team_elo_ratings WHERE team_id = %s "
            "ORDER BY season DESC LIMIT 1",
            (team_id,),
        )
    row = cur.fetchone()
    if row:
        return float(row[0])
    return INITIAL_ELO


def get_or_create_elo(
    conn: Any,
    team_id: int,
    team_name: str = "",
    season: str | None = None,
    league_tier: str | None = None,
) -> tuple[float, bool]:
    """获取或创建球队 Elo 记录。

    Args:
        conn: DB 连接
        team_id: 球队 ID
        team_name: 球队名称
        season: 赛季
        league_tier: 联赛级别

    Returns:
        (elo_rating, created) — 评分和是否为新创建
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id, elo_rating, matches_played FROM team_elo_ratings "
        "WHERE team_id = %s AND season IS NOT DISTINCT FROM %s",
        (team_id, season),
    )
    row = cur.fetchone()

    if row:
        return (float(row[1]), False)

    # 创建新记录
    init_elo = initial_elo_for_team(league_tier)
    cur.execute(
        """INSERT INTO team_elo_ratings
           (team_id, team_name, season, elo_rating, peak_elo, league_tier)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING elo_rating""",
        (team_id, team_name, season, init_elo, init_elo, league_tier or "other"),
    )
    conn.commit()
    return (init_elo, True)


def update_elo_ratings(
    conn: Any,
    home_team_id: int,
    away_team_id: int,
    home_goals: int,
    away_goals: int,
    match_id: int,
    match_date: str | None = None,
    season: str | None = None,
    league_tier: str | None = None,
) -> dict[str, Any]:
    """赛后更新两支球队的 Elo 评分。

    Args:
        conn: DB 连接
        home_team_id: 主队 ID
        away_team_id: 客队 ID
        home_goals: 主队进球
        away_goals: 客队进球
        match_id: 比赛 ID
        match_date: 比赛日期
        season: 赛季
        league_tier: 联赛级别

    Returns:
        更新结果 dict
    """
    # 获取当前 Elo
    home_elo, _ = get_or_create_elo(conn, home_team_id, "", season, league_tier)
    away_elo, _ = get_or_create_elo(conn, away_team_id, "", season, league_tier)

    # 计算新 Elo
    new_home, new_away = process_match_results(
        home_elo, away_elo, home_goals, away_goals, league_tier
    )

    if home_goals > away_goals:
        result = "H"
    elif home_goals == away_goals:
        result = "D"
    else:
        result = "A"

    goal_diff = home_goals - away_goals
    k = league_k_factor(league_tier)
    elo_delta = abs(new_home - home_elo) + abs(new_away - away_elo)

    # 更新主队
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE team_elo_ratings SET
               elo_rating = %s,
               matches_played = matches_played + 1,
               peak_elo = GREATEST(peak_elo, %s),
               home_win_pct = (home_win_pct * matches_played + %s) / (matches_played + 1),
               last_match_date = %s,
               updated_at = NOW()
               WHERE team_id = %s AND season IS NOT DISTINCT FROM %s""",
            (
                new_home,
                new_home,
                1.0 if result == "H" else (0.5 if result == "D" else 0.0),
                match_date,
                home_team_id,
                season,
            ),
        )
        # 更新客队
        cur.execute(
            """UPDATE team_elo_ratings SET
               elo_rating = %s,
               matches_played = matches_played + 1,
               peak_elo = GREATEST(peak_elo, %s),
               away_win_pct = (away_win_pct * matches_played + %s) / (matches_played + 1),
               last_match_date = %s,
               updated_at = NOW()
               WHERE team_id = %s AND season IS NOT DISTINCT FROM %s""",
            (
                new_away,
                new_away,
                1.0 if result == "A" else (0.5 if result == "D" else 0.0),
                match_date,
                away_team_id,
                season,
            ),
        )

    # 写入日志
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO elo_update_logs
               (match_id, home_team_id, away_team_id,
                home_elo_before, away_elo_before,
                home_elo_after, away_elo_after,
                home_goals, away_goals, result, goal_diff,
                k_factor, elo_delta, season, league_tier)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                match_id,
                home_team_id,
                away_team_id,
                home_elo,
                away_elo,
                new_home,
                new_away,
                home_goals,
                away_goals,
                result,
                goal_diff,
                k,
                elo_delta,
                season,
                league_tier,
            ),
        )

    conn.commit()

    return {
        "match_id": match_id,
        "home_elo_before": home_elo,
        "home_elo_after": new_home,
        "away_elo_before": away_elo,
        "away_elo_after": new_away,
        "result": result,
        "elo_delta": round(elo_delta, 2),
    }


# —— 自测 ——

if __name__ == "__main__":
    # 基本计算测试
    print("=== Elo 基础测试 ===")
    a, b = 1500, 1500
    e = expected_score(a, b)
    print(f"  同分 1500 vs 1500: E_A = {e:.4f}")
    assert abs(e - 0.5) < 0.01

    e2 = expected_score(1600, 1400)
    print(f"  1600 vs 1400: E_A = {e2:.4f}")
    assert e2 > 0.5

    # 比赛更新测试
    print("\n=== 比赛更新 ===")
    h_elo, a_elo = 1500, 1500
    new_h, new_a = process_match_results(h_elo, a_elo, 2, 1, "top5")
    print(f"  主胜 2-1: {h_elo}→{new_h}, {a_elo}→{new_a}")
    assert new_h > h_elo
    assert new_a < a_elo

    new_h, new_a = process_match_results(h_elo, a_elo, 1, 1, "top5")
    print(f"  平局 1-1: {h_elo}→{new_h}, {a_elo}→{new_a}")

    new_h, new_a = process_match_results(h_elo, a_elo, 0, 3, "top5")
    print(f"  客胜 0-3: {h_elo}→{new_h}, {a_elo}→{new_a}")
    assert new_h < h_elo

    # Elo → 1x2
    print("\n=== Elo → 1x2 ===")
    probs = run_elo_1x2_prediction(1600, 1400)
    for k, v in probs.items():
        print(f"  {k}: {v:.4f}")
    assert probs["3"] > probs["0"]

    probs = run_elo_1x2_prediction(1500, 1500)
    print(f"  同分: 3={probs['3']:.4f}, 1={probs['1']:.4f}, 0={probs['0']:.4f}")
    assert probs["3"] > probs["0"], "同分时主场应占优"

    print("\n✅ 所有测试通过")
