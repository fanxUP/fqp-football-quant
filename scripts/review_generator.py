"""日报/周报/月报文本生成。

All functions take aggregated dicts and return Chinese narrative strings.
No database access — pure text formatting.
"""

from __future__ import annotations


def daily_summary(data: dict) -> str:
    """Generate a 3-5 sentence Chinese daily review narrative."""
    date = data.get("review_date", "—")
    match_count = data.get("official_match_count", 0)
    analyzable = data.get("analyzable_match_count", 0)
    recommended = data.get("recommended_match_count", 0)
    sim_count = data.get("simulation_ticket_count", 0)
    real_count = data.get("real_ticket_count", 0)
    suggested = data.get("suggested_stake", 0)
    actual = data.get("actual_stake", 0)
    sim_pl = data.get("simulation_profit_loss", 0)
    real_pl = data.get("real_profit_loss", 0)
    sim_roi = data.get("simulation_roi", 0)
    real_roi = data.get("real_roi", 0)
    budget_rate = data.get("budget_usage_rate", 0)
    deviation = data.get("deviation_rate", 0)
    top_errors = data.get("top_error_types", "")

    parts = [
        f"{date}：今日共 {match_count} 场官方比赛，其中 {analyzable} 场有完整数据。",
        f"系统推荐 {recommended} 场比赛，生成 {sim_count} 张模拟票，用户实际投入 {real_count} 张实票。",
        f"建议投入 {suggested} 元，实际投入 {actual} 元，预算使用率 {budget_rate:.1%}。",
    ]

    if sim_count > 0 or real_count > 0:
        parts.append(
            f"模拟盈亏 {sim_pl:+.2f} 元（ROI {sim_roi:.1%}），"
            f"实票盈亏 {real_pl:+.2f} 元（ROI {real_roi:.1%}）。"
        )
    else:
        parts.append("今日无入场票单，模拟与实票均无盈亏。")

    if deviation > 0.01:
        parts.append(f"用户偏离率 {deviation:.1%}，需关注执行一致性。")

    if top_errors:
        parts.append(f"主要错因：{top_errors}。")

    return "".join(parts)


def weekly_summary(data: dict) -> str:
    """Generate a 4-6 sentence Chinese weekly review narrative."""
    week_start = data.get("week_start", "—")
    week_end = data.get("week_end", "—")
    total_stake = data.get("total_stake", 0)
    total_prize = data.get("total_prize", 0)
    profit_loss = data.get("profit_loss", 0)
    roi = data.get("roi", 0)
    max_drawdown = data.get("max_drawdown", 0)
    best_play = data.get("best_play_type", "—")
    worst_play = data.get("worst_play_type", "—")
    best_league = data.get("best_league", "—")
    worst_league = data.get("worst_league", "—")
    losing_days = data.get("losing_days_count", 0)
    sim_vs_real_gap = data.get("simulation_vs_real_gap", "—")
    strategy = data.get("strategy_suggestion", "")

    parts = [
        f"{week_start} 至 {week_end}：总投入 {total_stake:.2f} 元，"
        f"总返奖 {total_prize:.2f} 元，盈亏 {profit_loss:+.2f} 元，ROI {roi:.1%}。",
        f"最大回撤 {max_drawdown:.1%}，共有 {losing_days} 天亏损。",
    ]

    if best_play != "—" or worst_play != "—":
        parts.append(f"最佳玩法：{best_play}，最差玩法：{worst_play}。")
    if best_league != "—" or worst_league != "—":
        parts.append(f"最佳联赛：{best_league}，最差联赛：{worst_league}。")

    parts.append(f"模拟与实票差距：{sim_vs_real_gap}。")

    if strategy:
        parts.append(f"建议调整：{strategy}")

    return "".join(parts)


def monthly_summary(data: dict) -> str:
    """Generate a 5-8 sentence Chinese monthly review narrative."""
    month = data.get("month", "—")
    total_stake = data.get("total_stake", 0)
    total_prize = data.get("total_prize", 0)
    profit_loss = data.get("profit_loss", 0)
    roi = data.get("roi", 0)
    max_drawdown = data.get("max_drawdown", 0)
    losing_streak = data.get("longest_losing_streak", 0)
    best_pool = data.get("best_strategy_pool", "—")
    worst_pool = data.get("worst_strategy_pool", "—")
    calibration = data.get("model_calibration_score", 0)
    top_errors = data.get("top_error_categories", "")
    next_plan = data.get("next_month_plan", "")

    parts = [
        f"{month}月度总结：总投入 {total_stake:.2f} 元，"
        f"总返奖 {total_prize:.2f} 元，净盈亏 {profit_loss:+.2f} 元，"
        f"月 ROI {roi:.1%}。",
        f"最大回撤 {max_drawdown:.1%}，最长连亏 {losing_streak} 天。",
    ]

    if best_pool != "—" or worst_pool != "—":
        parts.append(f"最佳策略池：{best_pool}，最差策略池：{worst_pool}。")

    if calibration > 0:
        parts.append(f"模型校准分 {calibration:.3f}（越接近 0 越好）。")
    else:
        parts.append("模型校准分暂无（需要更多赛果数据）。")

    if top_errors:
        parts.append(f"本月主要错因：{top_errors}。")

    if next_plan:
        parts.append(f"下月计划：{next_plan}")

    return "".join(parts)


def error_analysis_text(errors: list[dict]) -> str:
    """Aggregate a list of error dicts into a Chinese diagnostic sentence.

    Each error dict should have: error_type, error_level, root_cause.
    Returns a summary of the top 3 error categories.
    """
    if not errors:
        return "本期无预测错因记录。"

    from collections import Counter

    type_counts: Counter = Counter()
    for e in errors:
        type_counts[e.get("error_type", "UNKNOWN")] += 1

    labels = {
        "MODEL_OVERCONFIDENCE": "模型过度自信",
        "DRAW_UNDERESTIMATED": "平局低估",
        "FAVOURITE_OVERVALUED": "强队高估/方向反向",
        "ODDS_DROP_AFTER_RECOMMENDATION": "赔率临场跳变",
        "INJURY_DATA_MISSING": "伤停数据缺失",
        "PARLAY_CORRELATION_HIGH": "串关相关性过高",
        "USER_CHANGED_OPTION": "用户改选",
        "USER_OVER_STAKED": "用户超注",
        "USER_CHASED_LOSS": "用户追损",
    }

    top3 = type_counts.most_common(3)
    parts = [f"共 {len(errors)} 条错因记录。"]
    for i, (etype, count) in enumerate(top3):
        label = labels.get(etype, etype)
        parts.append(f"第{i + 1}：{label} × {count} 次。")

    return "".join(parts)
