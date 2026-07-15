"""Recommendation candidate job — competition agent edition.

依据「足彩推荐依据框架」重构：
  1. 只选正 EV 方向（模型概率 > 市场隐含概率）
  2. 每场只选 1 个最优方向
  3. 四池分层：主策略池 / 防守池 / 价值池 / 小额进攻池
  4. 2串1 优先，3串1 小额（框架 §8.5）
  5. 平局风险检测降权（框架 §7.3）
  6. 常规资金池不强花 ¥500；有正 EV 但未过常规风控时，最小 2 元虚拟观察票留作竞赛样本

Daily budget: ¥500 max, unused portion resets at 23:59.
"""

from __future__ import annotations

import os
from datetime import datetime
from itertools import combinations
from math import floor
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.competition_storage import AGENT_DAILY_BUDGET
from scripts.daily_decision_storage import upsert_agent_daily_decision
from scripts.model_storage import store_simulation_ticket
from scripts.recommendation_prediction_loader import load_actionable_predictions


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _business_today():
    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone_name)).date()


def _record_daily_decision(result: dict[str, Any] | None = None, error: str | None = None) -> None:
    tickets = int((result or {}).get("tickets") or 0)
    total_stake = float((result or {}).get("total_stake") or 0)
    if error:
        status = "failed"
        reason = f"推荐任务执行失败：{error}"
    elif tickets > 0:
        status = "purchased"
        reason = (result or {}).get("note") or f"已创建 {tickets} 张 Agent 虚拟票"
    else:
        status = "abstained"
        reason = (result or {}).get("note") or "没有候选通过数据质量与风险门槛，今日不投注"
    with get_db() as conn:
        upsert_agent_daily_decision(
            conn,
            decision_date=_business_today(),
            status=status,
            total_stake=total_stake,
            reason=reason,
        )


def _official_stake(value: float) -> float:
    """Round a virtual stake down to the official 2-yuan unit."""
    return float(floor(max(0.0, value) / STAKE_UNIT) * STAKE_UNIT)


def _payout_cap(match_count: int) -> float:
    if match_count <= 1:
        return 100_000.0
    if match_count <= 3:
        return 200_000.0
    if match_count <= 5:
        return 500_000.0
    return 1_000_000.0


# ── Selection config ──

ALL_MODELS = ["market_baseline", "elo_rating", "dixon_coles", "maher_poisson"]

MIN_QUALITY = 50
MIN_CONFIDENCE = 0.20
MIN_STAKE = 2.0
STAKE_UNIT = 2.0


def _no_candidate_note(
    *,
    total_predictions: int,
    rejection_counts: dict[str, int],
    minimum_quality: int,
) -> str:
    """Explain the actual hard gate that removed all recommendation candidates."""
    quality_rejections = rejection_counts.get("data_quality", 0)
    if quality_rejections == total_predictions and total_predictions > 0:
        return (
            f"数据完整度不足：{quality_rejections} 条预测未达到 "
            f"{minimum_quality} 分门槛，今日不投注"
        )
    if rejection_counts.get("non_positive_ev", 0) == total_predictions:
        return "无正 EV 候选，今日不投注，未使用额度日终清空"
    if quality_rejections > 0:
        return (
            f"数据完整度不足：{quality_rejections}/{total_predictions} 条预测未达到 "
            f"{minimum_quality} 分门槛，其余候选也未通过风控，今日不投注"
        )
    return "候选未通过置信度、赔率质量或风险门槛，今日不投注"


def _ticket_generation_note(
    *,
    tickets_created: int,
    candidate_count: int,
    observation_fallback: bool = False,
) -> str:
    """Describe the terminal buy-or-abstain decision after pool assignment."""
    if observation_fallback:
        return "常规资金池未放行，已用 2 元生成 1 张高风险虚拟观察票，用于 Agent 竞赛与复盘"
    if tickets_created > 0:
        return f"已创建 {tickets_created} 张 Agent 虚拟票"
    if candidate_count > 0:
        return f"发现 {candidate_count} 个正 EV 候选，但均未通过资金池风险与置信度门槛，今日不投注"
    return "没有候选通过数据质量与风险门槛，今日不投注"


def _build_competition_observation_ticket(
    candidates: list[dict[str, Any]],
    *,
    single_allowed: set[tuple[int, str]],
    pass_allowed: set[tuple[int, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Build one minimum-stake virtual ticket when standard pools reject all candidates.

    The observation ticket never bypasses official market availability. It prefers
    a sellable single; otherwise it uses two distinct open-market selections.
    """
    eligible_candidates = [
        candidate for candidate in candidates if float(candidate.get("sp_value") or 0) > 0
    ]
    single_candidate = next(
        (
            candidate
            for candidate in eligible_candidates
            if (candidate["match_id"], candidate["play_type"]) in single_allowed
        ),
        None,
    )
    if single_candidate:
        selected = [single_candidate]
        pass_type = "single"
    else:
        selected = []
        seen_matches: set[int] = set()
        for candidate in eligible_candidates:
            market_key = (candidate["match_id"], candidate["play_type"])
            if market_key not in pass_allowed:
                continue
            if candidate["match_id"] in seen_matches:
                continue
            selected.append(candidate)
            seen_matches.add(candidate["match_id"])
            if len(selected) == 2:
                break
        if len(selected) < 2:
            return None
        pass_type = "2x1"

    combined_sp = 1.0
    combined_ev = 1.0
    for candidate in selected:
        combined_sp *= float(candidate["sp_value"])
        combined_ev *= float(candidate["ev"]) + 1
    combined_ev -= 1
    stake = MIN_STAKE
    ticket = {
        "strategy_pool": "agent_competition_observation",
        "ticket_type": "single" if pass_type == "single" else "parlay",
        "pass_type": pass_type,
        "suggested_stake": stake,
        "multiple": 1,
        "bet_count": 1,
        "estimated_return": round(
            min(stake * combined_sp, _payout_cap(len(selected))),
            2,
        ),
        "max_return": round(
            min(stake * combined_sp, _payout_cap(len(selected))),
            2,
        ),
        "expected_value": round(combined_ev, 4),
        "risk_level": "high",
        "ticket_status": "generated",
        "rule_metadata": {
            "source": "sporttery_rules",
            "virtual_competition": True,
            "observation_fallback": True,
        },
    }
    return ticket, selected


def _market_allows_pass(raw_json: dict[str, Any] | None) -> bool:
    """Read the official all-up capability retained in the market source payload."""
    pool = (raw_json or {}).get("_pool") or {}
    for field in ("allUp", "bettingAllup", "cbtAllUp", "intAllUp"):
        value = pool.get(field)
        if value is True or value == 1 or value == "1":
            return True
    return False


# ── 四池分层配置（框架 §9.1） ──
POOL_CONFIG: list[dict[str, Any]] = [
    {
        "name": "main",
        "label": "主策略池",
        "budget": 180.0,
        "max_per_ticket": 60.0,
        "risk_max": 0.08,
        "min_confidence": 0.40,
        "min_ev": 0.03,
    },
    {
        "name": "defense",
        "label": "防守池",
        "budget": 100.0,
        "max_per_ticket": 50.0,
        "risk_max": 0.15,
        "min_confidence": 0.30,
        "min_ev": 0.01,
    },
    {
        "name": "value",
        "label": "价值池",
        "budget": 70.0,
        "max_per_ticket": 35.0,
        "risk_max": 0.25,
        "min_confidence": 0.25,
        "min_ev": 0.03,
    },
    {
        "name": "attack",
        "label": "小额进攻池",
        "budget": 40.0,
        "max_per_ticket": 20.0,
        "risk_max": 0.50,
        "min_confidence": 0.20,
        "min_ev": 0.05,
    },
]

# ── 串关配置（框架 §8.5） ──
#   - 2串1 优先
#   - 3串1 小额（最多 ¥30）
#   - 不建议多场热门硬串（单场 SP < 1.30 的不参与串关）
#   - 不建议全部选深盘让胜

PARLAY_BUDGET = 80.0  # 串关总预算
PARLAY_2X1_MAX_STAKE = 40.0  # 2串1 单票上限
PARLAY_3X1_MAX_STAKE = 20.0  # 3串1 单票上限
PARLAY_3X1_TOTAL_MAX = 30.0  # 3串1 总预算上限
PARLAY_MIN_COMBO_EV = 0.03  # 组合最低正EV
PARLAY_MIN_SP = 1.30  # 单场最低SP（防过热）
PARLAY_MAX_COMBO_SP = 15.0  # 组合SP上限
PARLAY_MIN_QUALITY = 60  # 串关数据质量要求更高


def _prediction_sp_value(prediction_row: tuple[Any, ...]) -> float:
    """Read SP from the fixed prediction query layout.

    The query places kickoff_time at index 15 and the latest SP at index 16.
    Keeping this mapping in one helper prevents datetime values from being
    accidentally converted to float when the query is edited.
    """
    value = prediction_row[16]
    return float(value or 0) if value else 0.0


def _market_sp_quality(
    predictions: list[tuple[Any, ...]],
) -> tuple[dict[tuple[int, str], bool], int]:
    """Evaluate odds quality independently for each match and play type."""
    market_values: dict[tuple[int, str], dict[str, float]] = {}
    for prediction in predictions:
        market_key = (prediction[1], prediction[3])
        market_values.setdefault(market_key, {})[prediction[4]] = _prediction_sp_value(prediction)

    quality: dict[tuple[int, str], bool] = {}
    for market_key, option_values in market_values.items():
        values = list(option_values.values())
        quality[market_key] = not (
            any(value <= 0 for value in values) or (len(values) >= 2 and len(set(values)) == 1)
        )
    valid_match_count = len(
        {match_id for (match_id, _play_type), is_valid in quality.items() if is_valid}
    )
    return quality, valid_match_count


# ── 平局风险检测（框架 §7.3） ──
DRAW_ODDS_THRESHOLD = 3.50
DRAW_PROB_GAP_THRESHOLD = 0.15

# ── 赔率结构风险（框架 §7.1 + §7.2） ──
# §7.2 热门过热：SP < 1.30 → 热门过热，风险上浮
OVERHEAT_SP = 1.30
DEEP_OVERHEAT_SP = 1.20
OVERHEAT_PENALTY = 0.05
DEEP_OVERHEAT_PENALTY = 0.08
# §7.1 SPF vs 让球矛盾：主胜很低但让胜很高 → "赢不穿"风险
ODDS_GAP_HOME_SP_MAX = 1.50  # SPF主胜低于此值才触发检查
ODDS_GAP_RQSPF_H_MIN = 2.20  # 让球主胜高于此值 = 让球深
ODDS_GAP_PENALTY = 0.05

# ── 联赛分级（框架 §4 + §10） ──
# Tier 1: 顶级联赛 → 数据充分、不确定性低
# Tier 2: 次级联赛 → 正常
# Tier 3: 小型联赛 → 数据不完整、冷门风险高
LEAGUE_TIERS: dict[str, int] = {
    # Tier 1: 五大联赛 + 欧冠 + 欧联
    "英超": 1,
    "English Premier League": 1,
    "西甲": 1,
    "Spanish La Liga": 1,
    "德甲": 1,
    "German Bundesliga": 1,
    "意甲": 1,
    "Italian Serie A": 1,
    "法甲": 1,
    "French Ligue 1": 1,
    "欧冠": 1,
    "UEFA Champions League": 1,
    "欧联": 1,
    "UEFA Europa League": 1,
    # Tier 2: 五大次级 + 荷葡巴日韩
    "英冠": 2,
    "English Championship": 2,
    "德乙": 2,
    "German 2. Bundesliga": 2,
    "西乙": 2,
    "Spanish Segunda Division": 2,
    "意乙": 2,
    "Italian Serie B": 2,
    "法乙": 2,
    "French Ligue 2": 2,
    "荷甲": 2,
    "Dutch Eredivisie": 2,
    "葡超": 2,
    "Portuguese Liga": 2,
    "巴甲": 2,
    "Brazilian Serie A": 2,
    "日职": 2,
    "Japanese J1 League": 2,
    "韩职": 2,
    "Korean K League 1": 2,
    "美职": 2,
    "American MLS": 2,
}
# Default tier if league not found → Tier 3 (highest risk)
LEAGUE_TIER_RISK = {1: -0.02, 2: 0.0, 3: 0.03}

TOTAL_MAX_BUDGET = sum(p["budget"] for p in POOL_CONFIG)


def _run_impl(dry_run: bool = False) -> dict[str, Any]:
    """Generate simulation ticket candidates for the competition agent."""
    if dry_run:
        return {"status": "dry_run", "message": "recommendation candidate (dry run)"}

    with get_db() as conn:
        # ── 0. Ensure daily budget plan exists ──
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_budget_plans (plan_date, total_budget, suggested_stake,
                                                 unused_budget, risk_mode, status)
                VALUES (timezone('Asia/Shanghai', NOW())::date, %s, 0.00, %s, 'balanced', 'active')
                ON CONFLICT (plan_date) DO NOTHING
                """,
                (AGENT_DAILY_BUDGET, AGENT_DAILY_BUDGET),
            )
        conn.commit()

        # ── 0b. Idempotency ──
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*), COALESCE(SUM(suggested_stake), 0)
                   FROM simulation_tickets
                   WHERE (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                         = timezone('Asia/Shanghai', NOW())::date"""
            )
            already, existing_stake = cur.fetchone()
        if already > 0:
            return {
                "status": "ok",
                "tickets": already,
                "total_stake": float(existing_stake or 0),
                "reused": True,
                "note": f"今日已存在 {already} 张 Agent 虚拟票，本次不重复创建",
            }

        # ── 1. Load latest actionable predictions with correct odds per option ──
        # Bug fix: mp.odds_snapshot_id points to a single snapshot row (one
        # option_code), so joining on os.id = mp.odds_snapshot_id gave every
        # prediction for a match the same SP value.
        # Fix: join via LATERAL on (match_id, play_type, mapped option_code).
        # NOTE: official_odds_snapshots uses 'h'/'d'/'a' while
        #       model_predictions uses '3'/'1'/'0' — must map.
        predictions = load_actionable_predictions(conn, ALL_MODELS)

        if not predictions:
            return {"status": "ok", "tickets": 0, "note": "no predictions from models"}

        # ── 2c. Filter by available markets (official_markets) ──
        # Only consider predictions for play types that are actually open for betting
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT match_id, play_type FROM official_markets
                WHERE match_id = ANY(%s) AND is_open = true
                """,
                (list({p[1] for p in predictions}),),
            )
            open_markets = {(row[0], row[1]) for row in cur.fetchall()}

        predictions = [p for p in predictions if (p[1], p[3]) in open_markets]
        if not predictions:
            return {"status": "ok", "tickets": 0, "note": "no predictions with open markets"}

        # ── 2b. SP 数据质量校验 ──
        # 检测每个 match 的 sp_value 异常:
        #   - NULL sp (无赔率数据)
        #   - 同一场三个方向 SP 完全相等 (数据损坏信号)
        match_sp_quality, valid_match_count = _market_sp_quality(predictions)
        bad_sp_markets = [market for market, ok in match_sp_quality.items() if not ok]
        if bad_sp_markets:
            # 不阻止所有推荐，但标记劣质场次
            pass

        # ── 2c. 最低比赛数检查 ──
        # 按框架 §9, 四池分散需要至少 4 场有效比赛
        MIN_MATCHES = 4
        training_observation_mode = valid_match_count < MIN_MATCHES

        # ── 3. Data quality map ──
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT match_id, data_completeness_score
                FROM match_feature_snapshots
                WHERE (match_id, snapshot_time) IN (
                    SELECT match_id, MAX(snapshot_time)
                    FROM match_feature_snapshots
                    GROUP BY match_id
                )
                """
            )
            quality_map = {row[0]: float(row[1] or 0) for row in cur.fetchall()}

        # ── 4. Build draw-risk map (平局风险检测 §7.3) ──
        match_ids = {p[1] for p in predictions}
        match_spf: dict[int, dict[str, float]] = {}

        for p in predictions:
            mid = p[1]
            opt_code = p[4]
            market_prob = float(p[6] or 0)
            if mid not in match_spf:
                match_spf[mid] = {}
            match_spf[mid][opt_code] = market_prob

        draw_risk_map: dict[int, float] = {}
        for mid, probs in match_spf.items():
            draw_penalty = 0.0
            home_prob = probs.get("3", 0)
            draw_prob = probs.get("1", 0)
            away_prob = probs.get("0", 0)

            if draw_prob >= 0.30:
                draw_penalty += 0.05
            if abs(home_prob - away_prob) < DRAW_PROB_GAP_THRESHOLD:
                draw_penalty += 0.03

            if draw_penalty > 0:
                draw_risk_map[mid] = min(draw_penalty, 0.08)

        # ── 4b. Build odds-structure risk map (§7.1 + §7.2) ──
        # Load RQSPF home odds for SPF-vs-handicap consistency check
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (os.match_id)
                    os.match_id, os.sp_value, os.handicap
                FROM official_odds_snapshots os
                WHERE os.play_type = 'rqspf'
                  AND os.option_code = 'h'
                  AND os.match_id = ANY(%s)
                ORDER BY os.match_id, os.snapshot_time DESC
                """,
                (list(match_ids),),
            )
            rqspf_map = {
                row[0]: {
                    "rqspf_home_sp": float(row[1]) if row[1] else 0,
                    "handicap": float(row[2]) if row[2] else 0,
                }
                for row in cur.fetchall()
            }

        # Build per-match odds risk penalties
        odds_risk_map: dict[int, float] = {}

        for p in predictions:
            mid = p[1]
            opt_code = p[4]
            sp_value = _prediction_sp_value(p)

            if mid in odds_risk_map:
                continue  # already computed

            penalty = 0.0
            flags: list[str] = []

            # §7.2 热门过热
            if sp_value < DEEP_OVERHEAT_SP:
                penalty += DEEP_OVERHEAT_PENALTY
                flags.append(f"极端热门 SP={sp_value:.2f}")
            elif sp_value < OVERHEAT_SP:
                penalty += OVERHEAT_PENALTY
                flags.append(f"过热 SP={sp_value:.2f}")

            # §7.1 SPF vs RQSPF 矛盾检测
            # 只检测我们可能投注的主胜方向
            rq_data = rqspf_map.get(mid)
            if rq_data and rq_data["rqspf_home_sp"] > 0:
                rq_home_sp = rq_data["rqspf_home_sp"]
                handicap = rq_data["handicap"]
                # 主胜 SP 很低，但让球后主胜 SP 较高 → 矛盾
                if sp_value < ODDS_GAP_HOME_SP_MAX and rq_home_sp > ODDS_GAP_RQSPF_H_MIN:
                    penalty += ODDS_GAP_PENALTY
                    flags.append(
                        f"SPF-让球矛盾: 主胜{sp_value:.2f} vs 让{handicap:+g}胜{rq_home_sp:.2f}"
                    )

            if penalty > 0:
                odds_risk_map[mid] = min(penalty, 0.10)

        # ── 4c. Compute per-match model-preferred direction from ALL predictions
        #        (before EV pre-filter, so strong model signals are not lost)
        match_best_direction: dict[int, str] = {}
        match_best_prob: dict[int, float] = {}
        for p in predictions:
            mid = p[1]
            opt_code = p[4]
            prob = float(p[5] or 0)
            if mid not in match_best_prob or prob > match_best_prob[mid]:
                match_best_prob[mid] = prob
                match_best_direction[mid] = opt_code

        # ── 5. Parse & pre-filter ──
        parsed: list[dict] = []
        rejection_counts: dict[str, int] = {}

        def reject(reason: str) -> None:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        for p in predictions:
            (
                pred_id,
                match_id,
                _mv_id,
                play_type,
                opt_code,
                model_prob,
                market_prob,
                ev,
                confidence,
                risk,
                snap_id,
                feature_snapshot_id,
                home,
                away,
                league,
                _kickoff_time,
                sp_value,
                model_name,
            ) = (
                p[0],
                p[1],
                p[2],
                p[3],
                p[4],
                float(p[5] or 0),
                float(p[6] or 0),
                float(p[7] or 0),
                float(p[8] or 0),
                float(p[9] or 0),
                p[10],
                p[11],
                p[12],
                p[13],
                p[14],
                p[15],
                _prediction_sp_value(p),
                p[17],
            )

            quality = quality_map.get(match_id, 0)

            # 硬门槛
            if quality < MIN_QUALITY:
                reject("data_quality")
                continue
            if confidence < MIN_CONFIDENCE:
                reject("confidence")
                continue
            if ev <= 0 and not training_observation_mode:
                reject("non_positive_ev")
                continue

            # SP 数据质量：跳过 sp_value 异常的场次
            if not match_sp_quality.get((match_id, play_type), False):
                reject("odds_quality")
                continue

            # 模型-市场偏差过大时降级 confidence (模型盲区检测)
            deviation = abs(model_prob - market_prob)
            MODEL_MARKET_DEVIATION_WARN = 0.30
            if deviation > MODEL_MARKET_DEVIATION_WARN:
                confidence -= 0.10  # 大幅偏离降低置信度
                if confidence < MIN_CONFIDENCE:
                    reject("model_market_deviation")
                    continue

            # 多维风险综合（框架 §10）：
            # 原始模型风险 + 平局风险 + 赔率结构风险 + 联赛级别风险
            league_tier = LEAGUE_TIERS.get(league, 3)
            league_risk = LEAGUE_TIER_RISK.get(league_tier, 0.03)
            effective_risk = (
                risk + draw_risk_map.get(match_id, 0) + odds_risk_map.get(match_id, 0) + league_risk
            )

            parsed.append(
                {
                    "prediction_id": pred_id,
                    "match_id": match_id,
                    "play_type": play_type,
                    "option_code": opt_code,
                    "option_name": _option_label(opt_code, play_type),
                    "model_probability": model_prob,
                    "market_probability": market_prob,
                    "ev": ev,
                    "confidence_score": confidence,
                    "risk_score": effective_risk,
                    "raw_risk_score": risk,
                    "odds_snapshot_id": snap_id,
                    "feature_snapshot_id": feature_snapshot_id,
                    "sp_value": sp_value,
                    "home_team": home,
                    "away_team": away,
                    "league": league,
                    "model_name": model_name,
                    "data_quality": quality,
                    "draw_risk": draw_risk_map.get(match_id, 0),
                    "odds_risk": odds_risk_map.get(match_id, 0),
                    "league_tier": league_tier,
                }
            )

        if not parsed:
            return {
                "status": "ok",
                "tickets": 0,
                "total_predictions": len(predictions),
                "rejection_counts": rejection_counts,
                "note": _no_candidate_note(
                    total_predictions=len(predictions),
                    rejection_counts=rejection_counts,
                    minimum_quality=MIN_QUALITY,
                ),
            }

        # ── 6. Per-match: pick single best direction ──
        #    match_best_direction / match_best_prob were computed in step 4c
        #    from ALL predictions (before EV pre-filter).
        # 6a. Pick best EV candidate, but respect strong model signals
        STRONG_MODEL_THRESHOLD = 0.50  # model says >50%, don't bet against it
        by_match: dict[int, dict] = {}
        direction_conflicts: list[dict] = []

        for c in parsed:
            mid = c["match_id"]
            best_dir = match_best_direction.get(mid, "")
            best_prob = match_best_prob.get(mid, 0)

            # If model strongly favors one direction, only allow that direction
            if best_prob >= STRONG_MODEL_THRESHOLD and c["option_code"] != best_dir:
                direction_conflicts.append(
                    {
                        "match_id": mid,
                        "home": c["home_team"],
                        "away": c["away_team"],
                        "rejected_direction": c["option_code"],
                        "rejected_ev": round(c["ev"], 4),
                        "model_direction": best_dir,
                        "model_probability": round(best_prob, 4),
                    }
                )
                continue

            if mid not in by_match or c["ev"] > by_match[mid]["ev"]:
                by_match[mid] = c

        if training_observation_mode:
            # Training data should cover independent market views. Keep the
            # best direction per match and play type instead of collapsing all
            # markets into one choice per match.
            by_market: dict[tuple[int, str], dict] = {}
            for c in parsed:
                key = (c["match_id"], c["play_type"])
                if key not in by_market or c["ev"] > by_market[key]["ev"]:
                    by_market[key] = c
            candidates = sorted(by_market.values(), key=lambda c: c["ev"], reverse=True)
        else:
            candidates = sorted(by_match.values(), key=lambda c: c["ev"], reverse=True)

        # Training mode spends the fixed daily virtual bankroll aggressively.
        # These are all Agent observations; EV is recorded for learning and is
        # not used as a hard rejection rule.
        if training_observation_mode and candidates:
            observation_tickets = 0
            observation_stake = 0.0
            daily_budget = AGENT_DAILY_BUDGET
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT match_id, play_type FROM official_markets WHERE is_single_allowed = true"
                )
                single_allowed = {(row[0], row[1]) for row in cur.fetchall()}
            single_candidates = [
                c for c in candidates if (c["match_id"], c["play_type"]) in single_allowed
            ]
            singles_budget = round(daily_budget * 0.60, 2) if single_candidates else 0.0
            combo_budget = round(daily_budget - singles_budget, 2)
            base_single_stake = (
                _official_stake(singles_budget / len(single_candidates))
                if single_candidates
                else 0.0
            )
            single_stakes = [base_single_stake] * len(single_candidates)
            if single_stakes:
                single_stakes[-1] = _official_stake(singles_budget - sum(single_stakes[:-1]))
            for c, stake in zip(single_candidates, single_stakes, strict=False):
                ticket_multiple = max(2, int(stake / 2))
                ticket = {
                    "strategy_pool": "agent_training_observation",
                    "ticket_type": "training_observation",
                    "pass_type": "single",
                    "suggested_stake": stake,
                    # Official竞彩倍数 is 2-99; use the minimum training
                    # multiplier and express the remaining budget as the
                    # number of generated tickets.
                    "multiple": ticket_multiple,
                    "bet_count": 1,
                    "estimated_return": round(min(stake * c["sp_value"], _payout_cap(1)), 2),
                    "max_return": round(min(stake * c["sp_value"], _payout_cap(1)), 2),
                    "expected_value": round(c["ev"], 4),
                    "risk_level": "observation",
                    "ticket_status": "generated",
                    "rule_metadata": {"source": "sporttery_rules", "single_eligible_checked": True},
                }
                # Agent observations belong to the competition/agent ledger,
                # not the user's manual simulator ledger.
                if store_simulation_ticket(conn, ticket, [_make_item(c)]):
                    observation_tickets += 1
                    observation_stake += stake
            if len(candidates) >= 2:
                combos_2 = _build_parlays(candidates, 2)
                if not combos_2:
                    combos_2 = [
                        {
                            "candidates": list(pair),
                            "combined_sp": pair[0]["sp_value"] * pair[1]["sp_value"],
                            "combined_ev": pair[0]["ev"] + pair[1]["ev"],
                        }
                        for pair in combinations(candidates, 2)
                        if len({c["match_id"] for c in pair}) == 2
                    ]
                combos = [("2x1", combo) for combo in combos_2[:3]]
                if len(candidates) >= 3:
                    combos_3 = _build_parlays(candidates, 3)
                    if not combos_3:
                        combos_3 = [
                            {
                                "candidates": list(triple),
                                "combined_sp": triple[0]["sp_value"]
                                * triple[1]["sp_value"]
                                * triple[2]["sp_value"],
                                "combined_ev": sum(c["ev"] for c in triple),
                            }
                            for triple in combinations(candidates, 3)
                            if len({c["match_id"] for c in triple}) == 3
                        ]
                    combos += [("3x1", combo) for combo in combos_3[:2]]
                combo_stakes = [_official_stake(combo_budget / len(combos))] * len(combos)
                combo_stakes[-1] = _official_stake(combo_budget - sum(combo_stakes[:-1]))
                for (pass_type, combo), combo_stake in zip(combos, combo_stakes, strict=False):
                    ticket_multiple = max(2, int(combo_stake / 2))
                    combo_items = [_make_item(c) for c in combo["candidates"]]
                    ticket = {
                        "strategy_pool": "agent_training_parlay",
                        "ticket_type": "training_observation",
                        "pass_type": pass_type,
                        "suggested_stake": combo_stake,
                        "multiple": ticket_multiple,
                        "bet_count": 1,
                        "estimated_return": round(
                            min(
                                combo_stake * combo["combined_sp"],
                                _payout_cap(len(combo["candidates"])),
                            ),
                            2,
                        ),
                        "max_return": round(
                            min(
                                combo_stake * combo["combined_sp"],
                                _payout_cap(len(combo["candidates"])),
                            ),
                            2,
                        ),
                        "expected_value": round(combo["combined_ev"], 4),
                        "risk_level": "aggressive_training",
                        "ticket_status": "generated",
                        "rule_metadata": {
                            "source": "sporttery_rules",
                            "parlay_min_matches": 2,
                            "unique_match_required": True,
                        },
                    }
                    if store_simulation_ticket(conn, ticket, combo_items):
                        observation_tickets += 1
                        observation_stake += combo_stake
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE daily_budget_plans
                       SET suggested_stake = COALESCE((
                               SELECT SUM(suggested_stake)
                               FROM simulation_tickets
                               WHERE budget_plan_id = daily_budget_plans.id
                                 AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                                     = timezone('Asia/Shanghai', NOW())::date
                           ), 0),
                           unused_budget = GREATEST(total_budget - COALESCE((
                               SELECT SUM(suggested_stake)
                               FROM simulation_tickets
                               WHERE budget_plan_id = daily_budget_plans.id
                                 AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                                     = timezone('Asia/Shanghai', NOW())::date
                           ), 0), 0),
                           updated_at = now()
                     WHERE plan_date = timezone('Asia/Shanghai', NOW())::date"""
                )
            conn.commit()
            return {
                "status": "ok",
                "tickets": observation_tickets,
                "total_stake": round(observation_stake, 2),
                "training_observation": True,
                "daily_virtual_budget": daily_budget,
                "valid_matches": valid_match_count,
                "note": f"训练模式：已激进使用每日虚拟资金 {daily_budget} 元，记录单场与过关样本",
            }

        # ── 7. Assign singles to pools ──
        pools: dict[str, list] = {p["name"]: [] for p in POOL_CONFIG}
        assigned: set[int] = set()

        for pool_cfg in POOL_CONFIG:
            for c in candidates:
                if c["match_id"] in assigned:
                    continue
                if (
                    c["risk_score"] <= pool_cfg["risk_max"]
                    and c["confidence_score"] >= pool_cfg["min_confidence"]
                    and c["ev"] >= pool_cfg["min_ev"]
                ):
                    pools[pool_cfg["name"]].append(c)
                    assigned.add(c["match_id"])

        # ── 8. Create single tickets per pool ──
        tickets_created = 0
        total_stake = 0.0
        pool_usage: dict[str, dict] = {}
        all_candidates_for_parlay: list[dict] = []  # collect for 串关 step

        for pool_cfg in POOL_CONFIG:
            pool_name = pool_cfg["name"]
            pool_budget = pool_cfg["budget"]
            candidates_in_pool = pools[pool_name]
            pool_stake = 0.0
            pool_tickets = 0

            if not candidates_in_pool:
                pool_usage[pool_name] = {
                    "label": pool_cfg["label"],
                    "budget": pool_budget,
                    "used": 0,
                    "tickets": 0,
                    "note": "无符合条件的候选",
                }
                continue

            n = len(candidates_in_pool)
            raw_stake = min(pool_budget / n, pool_cfg["max_per_ticket"])

            for i, c in enumerate(candidates_in_pool):
                remaining = pool_budget - pool_stake
                if remaining < MIN_STAKE:
                    break

                if i == n - 1:
                    stake = round(remaining, 2)
                else:
                    stake = min(raw_stake, remaining)

                stake = round(stake / STAKE_UNIT) * STAKE_UNIT
                if stake < MIN_STAKE:
                    continue
                stake = min(stake, pool_cfg["max_per_ticket"])

                est_return = stake * c["sp_value"]
                risk_level = _risk_label(c["risk_score"])

                ticket = {
                    "strategy_pool": f"agent_{pool_name}",
                    "ticket_type": "single",
                    "pass_type": "single",
                    "suggested_stake": round(stake, 2),
                    "multiple": 1,
                    "estimated_return": round(est_return, 2),
                    "max_return": round(est_return, 2),
                    "expected_value": round(c["ev"], 4),
                    "risk_level": risk_level,
                    "ticket_status": "generated",
                }

                items = [_make_item(c)]

                # Agent 虚拟购买：写入 Agent 专属竞赛票池。
                tid = _buy_ticket(conn, ticket, items)
                if tid:
                    tickets_created += 1
                    pool_stake += stake
                    pool_tickets += 1
                    all_candidates_for_parlay.append(c)

            total_stake += pool_stake
            pool_usage[pool_name] = {
                "label": pool_cfg["label"],
                "budget": pool_budget,
                "used": round(pool_stake, 2),
                "tickets": pool_tickets,
            }

        # ── 9. 串关组合（框架 §8.5） ──
        # 2串1 优先、3串1 小额
        parlay_tickets = 0
        parlay_stake = 0.0

        # Filter candidates eligible for parlays (stricter quality, exclude hot favorites)
        parlay_candidates = [
            c
            for c in candidates
            if c["sp_value"] >= PARLAY_MIN_SP
            and c["data_quality"] >= PARLAY_MIN_QUALITY
            and c["ev"] > 0
        ]

        if len(parlay_candidates) >= 2:
            # ── 2串1 ──
            combos_2x1 = _build_parlays(parlay_candidates, 2)

            remaining_parlay = PARLAY_BUDGET - parlay_stake
            n_2x1 = min(len(combos_2x1), 5)  # top 5 at most
            if n_2x1 > 0:
                stake_per_2x1 = min(
                    PARLAY_2X1_MAX_STAKE,
                    remaining_parlay / n_2x1,
                )
                for combo in combos_2x1[:n_2x1]:
                    if remaining_parlay < MIN_STAKE:
                        break
                    stake = round(stake_per_2x1 / STAKE_UNIT) * STAKE_UNIT
                    stake = min(stake, remaining_parlay)
                    if stake < MIN_STAKE:
                        continue

                    combined_sp = combo["combined_sp"]
                    combined_ev = combo["combined_ev"]
                    est_return = stake * combined_sp

                    ticket = {
                        "strategy_pool": "agent_parlay_2x1",
                        "ticket_type": "parlay",
                        "pass_type": "2x1",
                        "suggested_stake": round(stake, 2),
                        "multiple": 1,
                        "estimated_return": round(est_return, 2),
                        "max_return": round(est_return, 2),
                        "expected_value": round(combined_ev, 4),
                        "risk_level": "medium-high",
                        "ticket_status": "generated",
                    }

                    items = [_make_item(c) for c in combo["candidates"]]
                    tid = _buy_ticket(conn, ticket, items)
                    if tid:
                        tickets_created += 1
                        parlay_tickets += 1
                        parlay_stake += stake
                        remaining_parlay -= stake

            # ── 3串1（小额，框架 §8.5: "3串1小额"） ──
            if len(parlay_candidates) >= 3:
                combos_3x1 = _build_parlays(parlay_candidates, 3)

                remaining_3x1 = min(PARLAY_3X1_TOTAL_MAX, PARLAY_BUDGET - parlay_stake)
                n_3x1 = min(len(combos_3x1), 2)  # at most 2
                if n_3x1 > 0 and remaining_3x1 >= MIN_STAKE:
                    stake_per_3x1 = min(
                        PARLAY_3X1_MAX_STAKE,
                        remaining_3x1 / n_3x1,
                    )
                    for combo in combos_3x1[:n_3x1]:
                        if remaining_3x1 < MIN_STAKE:
                            break
                        stake = round(stake_per_3x1 / STAKE_UNIT) * STAKE_UNIT
                        stake = min(stake, remaining_3x1)
                        if stake < MIN_STAKE:
                            continue

                        combined_sp = combo["combined_sp"]
                        combined_ev = combo["combined_ev"]
                        est_return = stake * combined_sp

                        ticket = {
                            "strategy_pool": "agent_parlay_3x1",
                            "ticket_type": "parlay",
                            "pass_type": "3x1",
                            "suggested_stake": round(stake, 2),
                            "multiple": 1,
                            "estimated_return": round(est_return, 2),
                            "max_return": round(est_return, 2),
                            "expected_value": round(combined_ev, 4),
                            "risk_level": "high",
                            "ticket_status": "generated",
                        }

                        items = [_make_item(c) for c in combo["candidates"]]
                        tid = _buy_ticket(conn, ticket, items)
                        if tid:
                            tickets_created += 1
                            parlay_tickets += 1
                            parlay_stake += stake
                            remaining_3x1 -= stake

        total_stake += parlay_stake
        parlay_usage = {
            "budget": PARLAY_BUDGET,
            "used": round(parlay_stake, 2),
            "tickets": parlay_tickets,
        }

        # ── 9b. 竞赛最小观察票 ──
        # 常规四池仍保持原有风控；仅当正 EV 候选已通过数据与官方市场硬门槛，
        # 但全部被常规资金池拒绝时，以最小 2 元虚拟仓位留下可结算的竞赛样本。
        observation_fallback = False
        observation_usage = {"used": 0.0, "tickets": 0}
        if tickets_created == 0 and candidates:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT match_id, play_type, is_single_allowed, raw_json
                    FROM official_markets
                    WHERE match_id = ANY(%s)
                      AND is_open = true
                    """,
                    (list({candidate["match_id"] for candidate in candidates}),),
                )
                market_permissions = cur.fetchall()
                single_allowed = {(row[0], row[1]) for row in market_permissions if row[2]}
                pass_allowed = {
                    (row[0], row[1]) for row in market_permissions if _market_allows_pass(row[3])
                }
            observation = _build_competition_observation_ticket(
                candidates,
                single_allowed=single_allowed,
                pass_allowed=pass_allowed,
            )
            if observation:
                observation_ticket, observation_candidates = observation
                ticket_id = _buy_ticket(
                    conn,
                    observation_ticket,
                    [_make_item(candidate) for candidate in observation_candidates],
                )
                if ticket_id:
                    observation_fallback = True
                    tickets_created = 1
                    observation_stake = float(observation_ticket["suggested_stake"])
                    total_stake += observation_stake
                    observation_usage = {
                        "used": observation_stake,
                        "tickets": 1,
                        "pass_type": observation_ticket["pass_type"],
                    }

        # ── 10. Risk-flag summaries ──
        draw_flagged = [
            {
                "match_id": mid,
                "home": by_match[mid]["home_team"],
                "away": by_match[mid]["away_team"],
                "penalty": round(draw_risk_map[mid], 3),
            }
            for mid in draw_risk_map
            if mid in by_match
        ]
        odds_flagged = [
            {
                "match_id": mid,
                "home": by_match[mid]["home_team"],
                "away": by_match[mid]["away_team"],
                "penalty": round(odds_risk_map[mid], 3),
            }
            for mid in odds_risk_map
            if mid in by_match
        ]

        return {
            "status": "ok",
            "tickets": tickets_created,
            "note": _ticket_generation_note(
                tickets_created=tickets_created,
                candidate_count=len(candidates),
                observation_fallback=observation_fallback,
            ),
            "total_stake": round(total_stake, 2),
            "total_budget": AGENT_DAILY_BUDGET,
            "unused": round(AGENT_DAILY_BUDGET - total_stake, 2),
            "positive_ev_candidates": len(candidates),
            "total_predictions": len(predictions),
            "top_ev": round(candidates[0]["ev"], 6) if candidates else None,
            "pool_usage": pool_usage,
            "parlay_usage": parlay_usage,
            "observation_usage": observation_usage,
            "draw_risk_flags": draw_flagged,
            "odds_risk_flags": odds_flagged,
            "direction_conflicts": direction_conflicts,
        }


# ── Helpers ──


def _option_label(code: str, play_type: str = "spf") -> str:
    if play_type == "bqc" and len(code) == 2:
        labels = {"3": "胜", "1": "平", "0": "负"}
        return f"{labels.get(code[0], code[0])}{labels.get(code[1], code[1])}"
    if play_type == "zjq":
        return "7+球" if code in {"7", "7+"} else f"{code}球"
    if play_type == "bf":
        return code.replace("_h", "其他胜").replace("_d", "其他平").replace("_a", "其他负")
    if play_type == "rqspf":
        return {"3": "让胜", "1": "让平", "0": "让负"}.get(code, code)
    return {"3": "主胜", "1": "平", "0": "客胜"}.get(code, code)


def _risk_label(risk_score: float) -> str:
    if risk_score < 0.07:
        return "low"
    elif risk_score < 0.15:
        return "medium"
    elif risk_score < 0.25:
        return "medium-high"
    return "high"


def _make_item(c: dict) -> dict:
    """Build a ticket item dict from a candidate."""
    return {
        "match_id": c["match_id"],
        "odds_snapshot_id": c["odds_snapshot_id"],
        "model_prediction_id": c["prediction_id"],
        "feature_snapshot_id": c.get("feature_snapshot_id"),
        "play_type": c["play_type"],
        "option_code": c["option_code"],
        "option_name": c["option_name"],
        "sp_value": c["sp_value"],
        "model_probability": c["model_probability"],
        "market_probability": c["market_probability"],
        "ev": c["ev"],
        "confidence_score": c["confidence_score"],
        "risk_score": c["risk_score"],
        "odds_source": "official" if c["odds_snapshot_id"] else "synthetic_model",
    }


def run(dry_run: bool = False) -> dict[str, Any]:
    """Generate candidates and persist its multi-agent execution record."""
    run_id = None
    try:
        run_id = start_tracked_job(
            "recommendation_candidate",
            "recommendation_agent",
            {"dry_run": dry_run},
            dependencies=[] if dry_run else ["official_odds_snapshot", "model_prediction"],
        )
        result = _run_impl(dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        if not dry_run:
            _record_daily_decision(result=result)
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        if not dry_run:
            _record_daily_decision(error=str(exc))
        raise


def _build_parlays(candidates: list[dict], size: int) -> list[dict]:
    """Generate and rank parlays of given size.

    Returns list of {candidates, combined_sp, combined_ev} sorted by EV desc.
    """
    result: list[dict] = []
    seen_sets: set[frozenset] = set()

    for combo in combinations(candidates, size):
        # No duplicate matches
        match_ids = {c["match_id"] for c in combo}
        if len(match_ids) < size:
            continue

        # Dedup by match set
        key = frozenset(match_ids)
        if key in seen_sets:
            continue
        seen_sets.add(key)

        # Combined SP = product of individual SPs
        combined_sp = 1.0
        for c in combo:
            combined_sp *= c["sp_value"]

        if combined_sp > PARLAY_MAX_COMBO_SP:
            continue

        # Combined EV = ∏(EV_i + 1) - 1
        combined_ev = 1.0
        for c in combo:
            combined_ev *= c["ev"] + 1
        combined_ev -= 1

        if combined_ev < PARLAY_MIN_COMBO_EV:
            continue

        result.append(
            {
                "candidates": list(combo),
                "combined_sp": round(combined_sp, 3),
                "combined_ev": round(combined_ev, 4),
            }
        )

    result.sort(key=lambda x: x["combined_ev"], reverse=True)
    return result


def _buy_ticket(conn: Any, ticket: dict, items: list[dict]) -> int | None:
    """Create one Agent-owned virtual competition ticket.

    Args:
        conn: DB connection
        ticket: Ticket dict with suggested_stake, pass_type, multiple, etc.
        items: List of item dicts (match selections)
    Returns:
        New Agent ticket ID, or None on failure.
    """
    if ticket.get("suggested_stake", 0) <= 0:
        return None
    try:
        return store_simulation_ticket(conn, ticket, items)
    except Exception as e:
        conn.rollback()
        print(f"[_buy_ticket] error creating ticket: {e}")
        return None


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
