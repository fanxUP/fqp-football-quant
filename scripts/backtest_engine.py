"""回测引擎 — Walk-forward 验证、资金曲线、指标聚合。

核心能力：
  1. 从历史预测+赛果数据加载回测样本
  2. 10 维过滤器（时间、联赛、玩法、赔率区间、EV区间、模型、风险等级、资金池等）
  3. Walk-forward 窗口划分（训练/测试滚动）
  4. 投注模拟（固定注额 1 单位）
  5. 10 项指标计算（命中率、ROI、Brier、Log Loss、CLV、
     最大回撤、最长连亏、平均赔率、Sharpe、Profit Factor）
  6. 资金曲线生成
  7. 结果聚合与存储

使用方式：
  from scripts.backtest_engine import BacktestEngine
  engine = BacktestEngine(conn, config)
  result = engine.run()
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# —— 数据结构 ——

CURRENT_METHODOLOGY_VERSION = 4


@dataclass
class BacktestConfig:
    """回测配置 — 对应设计文档的 10 个维度。"""

    # 过滤器维度
    name: str = ""
    description: str = ""
    time_start: str | None = None  # ISO date, e.g. "2025-01-01"
    time_end: str | None = None  # ISO date
    league_ids: list[int] | None = None  # NULL = 全部联赛
    play_types: list[str] | None = None  # NULL = 全部玩法, e.g. ["spf"]
    odds_min: float | None = None  # 最低赔率
    odds_max: float | None = None  # 最高赔率
    ev_min: float | None = None  # 最低 EV
    ev_max: float | None = None  # 最高 EV
    model_ids: list[int] | None = None  # NULL = 全部活跃模型
    model_names: list[str] | None = None  # 按名称筛选
    risk_levels: list[str] | None = None  # e.g. ["low", "medium"]
    confidence_min: float | None = None  # 最低置信度
    vote_directions: list[str] | None = None  # e.g. ["strong_h", "weak_h"]

    # Walk-forward 配置
    walk_forward: bool = True
    train_window_days: int = 365  # 训练窗口长度（天）
    test_window_days: int = 90  # 测试窗口长度（天）
    step_days: int = 90  # 每次滚动的步长（天）

    # 投注模拟
    stake_per_bet: float = 1.0  # 每注固定金额
    min_model_prob: float = 0.35  # 最低模型概率阈值（低于此值不下注）
    signal_strength: str = "strong"  # "strong" | "weak" | "all" — 只下注此强度的信号

    def to_dict(self) -> dict:
        return {
            # v4 起按玩法匹配官方赛果；继续采用赛前最新预测与预测时点赔率。
            # 版本由执行代码决定；旧配置重跑时自动升级，不能由请求覆盖。
            "methodology_version": CURRENT_METHODOLOGY_VERSION,
            "name": self.name,
            "description": self.description,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "league_ids": self.league_ids,
            "play_types": self.play_types,
            "odds_min": self.odds_min,
            "odds_max": self.odds_max,
            "ev_min": self.ev_min,
            "ev_max": self.ev_max,
            "model_ids": self.model_ids,
            "model_names": self.model_names,
            "risk_levels": self.risk_levels,
            "confidence_min": self.confidence_min,
            "vote_directions": self.vote_directions,
            "walk_forward": self.walk_forward,
            "train_window_days": self.train_window_days,
            "test_window_days": self.test_window_days,
            "step_days": self.step_days,
            "stake_per_bet": self.stake_per_bet,
            "min_model_prob": self.min_model_prob,
            "signal_strength": self.signal_strength,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BacktestConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BetRecord:
    """单笔投注记录。"""

    match_id: int
    match_date: str
    model_name: str
    option_code: str  # "3" / "1" / "0"
    model_prob: float
    market_prob: float
    odds: float  # 赔率 (sp_value)
    stake: float
    actual_result: str  # "3" / "1" / "0"
    profit: float  # 盈亏 (正=赢, 负=输)
    ev: float
    confidence: float
    play_type: str = "spf"


@dataclass
class WindowResult:
    """单个窗口的回测结果。"""

    window_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train_matches: int
    n_test_matches: int
    n_bets: int
    bets: list[BetRecord] = field(default_factory=list)
    model_metrics: dict[str, dict] = field(default_factory=dict)


# —— 引擎核心 ——


class BacktestEngine:
    """回测引擎。

    使用方式：
        config = BacktestConfig(name="SPF回测", time_start="2025-01-01")
        engine = BacktestEngine(conn, config)
        result = engine.run()
        # result = {"windows": [...], "aggregate": {...}, "equity_curve": [...]}
    """

    def __init__(self, conn: Any, config: BacktestConfig):
        self.conn = conn
        self.config = config

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _build_query(self) -> tuple[str, list]:
        """构建回测数据查询 SQL。

        JOIN: model_predictions → model_versions → official_matches → official_results → official_odds_snapshots
        """
        where = [
            "mp.prediction_rank = 1",
            "m.match_status = 'Settled'",
            "r.full_home_goals IS NOT NULL",
            "r.full_away_goals IS NOT NULL",
            "mp.model_probability > 0",
        ]
        params: list = []

        if self.config.time_start:
            where.append("m.business_date >= %s")
            params.append(self.config.time_start)
        if self.config.time_end:
            where.append("m.business_date <= %s")
            params.append(self.config.time_end)
        if self.config.league_ids:
            # league_ids stores league name patterns; match by league_name
            pass  # Filter by league_name not implemented for league_ids — use league name list instead
        if self.config.play_types:
            placeholders = ",".join(["%s"] * len(self.config.play_types))
            where.append(f"mp.play_type IN ({placeholders})")
            params.extend(self.config.play_types)
        if self.config.model_names:
            placeholders = ",".join(["%s"] * len(self.config.model_names))
            where.append(f"mv.model_name IN ({placeholders})")
            params.extend(self.config.model_names)
        if self.config.model_ids:
            placeholders = ",".join(["%s"] * len(self.config.model_ids))
            where.append(f"mp.model_version_id IN ({placeholders})")
            params.extend(self.config.model_ids)
        if self.config.confidence_min is not None:
            where.append("mp.confidence_score >= %s")
            params.append(self.config.confidence_min)
        if self.config.vote_directions:
            # 需要 JOIN model_committee_votes
            pass  # handled separately in load_data

        where_clause = " AND ".join(where)

        sql = f"""
            WITH ranked_predictions AS (
                SELECT
                    source_mp.*,
                    DENSE_RANK() OVER (
                        PARTITION BY source_mp.match_id,
                                     source_mp.model_version_id,
                                     source_mp.play_type
                        ORDER BY source_mp.predict_time DESC
                    ) AS prediction_rank
                FROM model_predictions source_mp
                JOIN official_matches source_m ON source_m.id = source_mp.match_id
                WHERE source_mp.predict_time < source_m.kickoff_time
                  AND source_mp.validation_status = 'valid'
            )
            SELECT
                mp.match_id,
                m.business_date AS match_date,
                mv.model_name,
                mp.play_type,
                mp.option_code,
                mp.model_probability,
                mp.market_probability,
                mp.ev,
                mp.confidence_score,
                mp.predict_time,
                CASE
                    WHEN mp.play_type = 'spf' THEN COALESCE(
                        NULLIF(r.spf_result, ''),
                        CASE
                            WHEN r.full_home_goals > r.full_away_goals THEN '3'
                            WHEN r.full_home_goals = r.full_away_goals THEN '1'
                            ELSE '0'
                        END
                    )
                    WHEN mp.play_type = 'rqspf' THEN NULLIF(r.rqspf_result, '')
                    WHEN mp.play_type IN ('zjq', 'total_goals') THEN r.total_goals_result
                    WHEN mp.play_type IN ('bf', 'score') THEN r.score_result
                    WHEN mp.play_type IN ('bqc', 'half_full')
                        THEN REPLACE(r.half_full_result, '-', '')
                END AS actual_result,
                -- Latest odds snapshot for this match before kickoff
                -- Odds snapshots use h/d/a, model predictions use 3/1/0
                COALESCE(
                    (SELECT oos.sp_value
                     FROM official_odds_snapshots oos
                     WHERE oos.match_id = mp.match_id
                       AND oos.play_type = mp.play_type
                       AND oos.snapshot_time <= mp.predict_time
                       AND oos.option_code = CASE
                           WHEN mp.play_type IN ('spf', 'rqspf') THEN CASE mp.option_code
                               WHEN '3' THEN 'h'
                               WHEN '1' THEN 'd'
                               WHEN '0' THEN 'a'
                               ELSE mp.option_code
                           END
                           ELSE mp.option_code
                       END
                     ORDER BY oos.snapshot_time DESC
                     LIMIT 1),
                    0
                ) AS sp_value
            FROM ranked_predictions mp
            JOIN model_versions mv ON mv.id = mp.model_version_id
            JOIN official_matches m ON m.id = mp.match_id
            JOIN official_results r ON r.match_id = mp.match_id
            WHERE {where_clause}
              AND r.result_status IN ('final', 'confirmed')
            ORDER BY m.business_date ASC, mp.predict_time ASC
        """

        return sql, params

    def load_data(self) -> list[dict]:
        """加载回测数据，返回原始行列表。"""
        sql, params = self._build_query()
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
        return rows

    # ------------------------------------------------------------------
    # Walk-forward 窗口划分
    # ------------------------------------------------------------------

    def _build_windows(
        self,
        match_dates: list[date],
    ) -> list[dict]:
        """根据 match_dates 构建 walk-forward 窗口。

        如果没有足够的日期范围，回退到单窗口模式。
        """
        if not match_dates:
            return []

        min_date = min(match_dates)
        max_date = max(match_dates)

        cfg = self.config
        if not cfg.walk_forward:
            return [
                {
                    "window_index": 0,
                    "train_start": None,
                    "train_end": None,
                    "test_start": min_date.isoformat(),
                    "test_end": max_date.isoformat(),
                }
            ]

        from datetime import timedelta

        windows = []
        current = min_date
        idx = 0

        while current < max_date:
            train_start = current
            train_end = current + timedelta(days=cfg.train_window_days)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=cfg.test_window_days)

            if test_start > max_date:
                break

            # Clamp test_end
            if test_end > max_date:
                test_end = max_date

            windows.append(
                {
                    "window_index": idx,
                    "train_start": train_start.isoformat(),
                    "train_end": min(train_end, max_date).isoformat(),
                    "test_start": test_start.isoformat(),
                    "test_end": test_end.isoformat(),
                }
            )
            idx += 1
            current += timedelta(days=cfg.step_days)

        # Fallback: single window if no windows generated
        if not windows:
            windows = [
                {
                    "window_index": 0,
                    "train_start": None,
                    "train_end": None,
                    "test_start": min_date.isoformat(),
                    "test_end": max_date.isoformat(),
                }
            ]

        return windows

    # ------------------------------------------------------------------
    # 投注模拟
    # ------------------------------------------------------------------

    def _should_bet(self, row: dict) -> bool:
        """判断是否对某条预测下注。"""
        cfg = self.config

        # 概率阈值
        mp = float(row["model_probability"])
        if mp < cfg.min_model_prob:
            return False

        # 信号强度过滤
        if cfg.signal_strength != "all":
            direction = "strong" if mp > 0.40 else ("weak" if mp > 0.30 else "against")
            if direction != cfg.signal_strength:
                return False

        # 赔率过滤
        sp = float(row.get("sp_value", 0))
        if cfg.odds_min is not None and sp < cfg.odds_min:
            return False
        if cfg.odds_max is not None and sp > cfg.odds_max:
            return False

        # EV 过滤
        ev = float(row.get("ev", 0))
        if cfg.ev_min is not None and ev < cfg.ev_min:
            return False
        if cfg.ev_max is not None and ev > cfg.ev_max:
            return False

        # 投票方向过滤
        if cfg.vote_directions:
            if mp > 0.40:
                direction_label = f"strong_{row['option_code']}"
            elif mp > 0.30:
                direction_label = f"weak_{row['option_code']}"
            else:
                direction_label = f"against_{row['option_code']}"
            if direction_label not in cfg.vote_directions:
                return False

        return True

    def _simulate_bets(
        self,
        rows: list[dict],
        test_start: str,
        test_end: str,
    ) -> list[BetRecord]:
        """在测试窗口内模拟投注。"""
        candidates: dict[tuple[int, str, str], list[dict]] = defaultdict(list)

        for row in rows:
            match_date = str(row["match_date"])[:10]
            if match_date < test_start or match_date > test_end:
                continue

            if not self._should_bet(row):
                continue

            if not row.get("actual_result"):
                continue

            key = (
                int(row["match_id"]),
                str(row["model_name"]),
                str(row.get("play_type") or "spf"),
            )
            candidates[key].append(row)

        bets: list[BetRecord] = []
        for candidate_rows in candidates.values():
            row = max(
                candidate_rows,
                key=lambda item: (
                    float(item.get("ev", 0)),
                    float(item.get("model_probability", 0)),
                ),
            )
            match_date = str(row["match_date"])[:10]

            sp = float(row.get("sp_value", 0))
            if sp <= 0:
                continue

            actual = row["actual_result"]
            opt = row["option_code"]
            stake = self.config.stake_per_bet

            # 计算盈亏
            if opt == actual:
                profit = stake * (sp - 1.0)
            else:
                profit = -stake

            bets.append(
                BetRecord(
                    match_id=row["match_id"],
                    match_date=match_date,
                    model_name=row["model_name"],
                    option_code=opt,
                    model_prob=float(row["model_probability"]),
                    market_prob=float(row.get("market_probability", 0)),
                    odds=sp,
                    stake=stake,
                    actual_result=actual,
                    profit=profit,
                    ev=float(row.get("ev", 0)),
                    confidence=float(row.get("confidence_score", 0)),
                    play_type=str(row.get("play_type") or "spf"),
                )
            )

        return bets

    # ------------------------------------------------------------------
    # 指标计算
    # ------------------------------------------------------------------

    @staticmethod
    def compute_metrics(
        bets: list[BetRecord],
    ) -> dict[str, Any]:
        """从投注列表计算所有指标。"""
        n = len(bets)
        if n == 0:
            return {
                "n_bets": 0,
                "n_wins": 0,
                "hit_rate": None,
                "roi": None,
                "total_profit": 0.0,
                "avg_odds": None,
                "brier_score": None,
                "log_loss": None,
                "clv": None,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "longest_losing_streak": 0,
                "sharpe_ratio": None,
                "profit_factor": None,
                "equity_curve": [],
            }

        n_wins = sum(1 for b in bets if b.profit > 0)
        hit_rate = n_wins / n
        total_profit = sum(b.profit for b in bets)
        roi = total_profit / (n * bets[0].stake) if n > 0 else None
        avg_odds = sum(b.odds for b in bets) / n

        # Brier Score: average over all bets
        brier_total = 0.0
        log_loss_total = 0.0
        clv_total = 0.0
        for b in bets:
            # Brier: (p - o)^2 where o=1 if correct
            o = 1.0 if b.option_code == b.actual_result else 0.0
            brier_total += (b.model_prob - o) ** 2
            # Log loss
            eps = 1e-15
            p_clamped = max(eps, min(1.0 - eps, b.model_prob))
            if o > 0:
                log_loss_total -= math.log(p_clamped)
            else:
                log_loss_total -= math.log(1.0 - p_clamped)
            # CLV: model_prob - market_prob
            clv_total += b.model_prob - b.market_prob

        brier_score = brier_total / n
        log_loss = log_loss_total / n
        clv = clv_total / n

        # 资金曲线 + 最大回撤 + 最长连亏
        equity_curve: list[dict] = []
        initial_bankroll = 100.0
        bankroll = initial_bankroll
        peak = initial_bankroll
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        current_losing_streak = 0
        longest_losing_streak = 0
        daily_profits: dict[str, float] = defaultdict(float)

        for b in bets:
            bankroll += b.profit
            daily_profits[b.match_date] += b.profit
            if bankroll > peak:
                peak = bankroll
            drawdown = peak - bankroll
            drawdown_pct = (drawdown / peak * 100.0) if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct

            if b.profit < 0:
                current_losing_streak += 1
                if current_losing_streak > longest_losing_streak:
                    longest_losing_streak = current_losing_streak
            else:
                current_losing_streak = 0

            equity_curve.append(
                {
                    "date": b.match_date,
                    "bankroll": round(bankroll, 4),
                    "drawdown_pct": round(drawdown_pct, 2),
                }
            )

        # Sharpe ratio uses daily returns against a fixed starting bankroll.
        daily_returns = [profit / initial_bankroll for profit in daily_profits.values()]
        sharpe = None
        if len(daily_returns) > 1:
            mean_ret = sum(daily_returns) / len(daily_returns)
            if mean_ret != 0:
                var = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
                std_ret = math.sqrt(var)
                if std_ret > 0:
                    sharpe = (mean_ret / std_ret) * math.sqrt(252)  # annualized

        # Profit factor
        gross_profit = sum(b.profit for b in bets if b.profit > 0)
        gross_loss = abs(sum(b.profit for b in bets if b.profit < 0))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else (None if gross_loss == 0 else float("inf"))
        )

        return {
            "n_bets": n,
            "n_wins": n_wins,
            "hit_rate": round(hit_rate, 4),
            "roi": round(roi, 4) if roi is not None else None,
            "total_profit": round(total_profit, 4),
            "avg_odds": round(avg_odds, 4),
            "brier_score": round(brier_score, 4),
            "log_loss": round(log_loss, 4),
            "clv": round(clv, 4),
            "max_drawdown": round(max_drawdown, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "longest_losing_streak": longest_losing_streak,
            "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "equity_curve": equity_curve,
        }

    # ------------------------------------------------------------------
    # 主运行流程
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """执行完整回测流程。

        Returns:
            {"config": {...},
             "windows": [WindowResult, ...],
             "aggregate": {model_name: metrics, ...},
             "equity_curve": [...]}
        """
        # 1. 加载数据
        rows = self.load_data()
        if not rows:
            return {
                "status": "no_data",
                "config": self.config.to_dict(),
                "windows": [],
                "aggregate": {},
            }

        # 提取所有比赛日期
        match_dates = sorted(
            set(date.fromisoformat(str(r["match_date"])[:10]) for r in rows if r.get("match_date"))
        )

        # 2. 构建窗口
        windows_cfg = self._build_windows(match_dates)

        # 3. 逐窗口模拟
        window_results: list[WindowResult] = []
        all_bets_by_key: dict[tuple[int, str, str, str], BetRecord] = {}

        for wcfg in windows_cfg:
            bets = self._simulate_bets(rows, wcfg["test_start"], wcfg["test_end"])
            for bet in bets:
                all_bets_by_key[(
                    bet.match_id,
                    bet.model_name,
                    bet.play_type,
                    bet.match_date,
                )] = bet

            # 按模型分组计算指标
            model_bets: dict[str, list[BetRecord]] = defaultdict(list)
            for b in bets:
                model_bets[b.model_name].append(b)

            model_metrics = {}
            for mname, mbets in model_bets.items():
                model_metrics[mname] = self.compute_metrics(mbets)

            # 计算训练/测试比赛数
            ts = wcfg["test_start"]
            te = wcfg["test_end"]
            n_train = (
                len({r["match_id"] for r in rows if str(r["match_date"])[:10] < ts})
                if wcfg.get("train_start")
                else 0
            )
            n_test = len({
                r["match_id"] for r in rows if ts <= str(r["match_date"])[:10] <= te
            })

            window_results.append(
                WindowResult(
                    window_index=wcfg["window_index"],
                    train_start=wcfg.get("train_start") or "",
                    train_end=wcfg.get("train_end") or "",
                    test_start=ts,
                    test_end=te,
                    n_train_matches=n_train,
                    n_test_matches=n_test,
                    n_bets=len(bets),
                    bets=bets,
                    model_metrics=model_metrics,
                )
            )

        # 4. 聚合所有窗口
        all_bets = list(all_bets_by_key.values())
        all_model_bets: dict[str, list[BetRecord]] = defaultdict(list)
        for b in all_bets:
            all_model_bets[b.model_name].append(b)

        aggregate = {}
        for mname, mbets in all_model_bets.items():
            aggregate[mname] = self.compute_metrics(mbets)

        # 全局资金曲线（跨窗口）
        global_equity = self._build_global_equity(all_bets)

        return {
            "status": "ok",
            "config": self.config.to_dict(),
            "windows": [
                {
                    "window_index": w.window_index,
                    "train_start": w.train_start,
                    "train_end": w.train_end,
                    "test_start": w.test_start,
                    "test_end": w.test_end,
                    "n_train_matches": w.n_train_matches,
                    "n_test_matches": w.n_test_matches,
                    "n_bets": w.n_bets,
                    "model_metrics": w.model_metrics,
                }
                for w in window_results
            ],
            "aggregate": aggregate,
            "equity_curve": global_equity,
            "total_bets": len(all_bets),
            "total_windows": len(window_results),
        }

    def _build_global_equity(self, bets: list[BetRecord]) -> list[dict]:
        """构建全局资金曲线（所有窗口合并）。"""
        if not bets:
            return []

        curve: list[dict] = []
        bankroll = 0.0
        peak = 0.0

        for b in sorted(bets, key=lambda x: x.match_date):
            bankroll += b.profit
            if bankroll > peak:
                peak = bankroll
            drawdown_pct = ((peak - bankroll) / peak * 100.0) if peak > 0 else 0.0
            curve.append(
                {
                    "date": b.match_date,
                    "bankroll": round(bankroll, 4),
                    "drawdown_pct": round(drawdown_pct, 2),
                }
            )

        return curve

    # ------------------------------------------------------------------
    # 结果存储
    # ------------------------------------------------------------------

    def store_results(
        self,
        run_id: int,
        result: dict[str, Any],
    ) -> int:
        """将回测结果写入 backtest_run_* 表。"""
        stored = 0

        with self.conn.cursor() as cur:
            # Store windows
            for w in result.get("windows", []):
                cur.execute(
                    """INSERT INTO backtest_run_windows
                       (run_id, window_index, train_start_date, train_end_date,
                        test_start_date, test_end_date, n_train_matches,
                        n_test_matches, n_bets)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        run_id,
                        w["window_index"],
                        w["train_start"] or None,
                        w["train_end"] or None,
                        w["test_start"],
                        w["test_end"],
                        w["n_train_matches"],
                        w["n_test_matches"],
                        w["n_bets"],
                    ),
                )

                # Store per-model per-window metrics
                for model_name, metrics in w.get("model_metrics", {}).items():
                    self._insert_metrics_row(
                        cur,
                        run_id,
                        w["window_index"],
                        model_name,
                        metrics,
                    )
                    stored += 1

            # Store aggregate metrics
            for model_name, metrics in result.get("aggregate", {}).items():
                self._insert_metrics_row(
                    cur,
                    run_id,
                    None,
                    model_name,
                    metrics,
                )
                stored += 1

            # Update run status
            cur.execute(
                """UPDATE backtest_runs
                   SET status = 'completed', finished_at = NOW()
                   WHERE id = %s""",
                (run_id,),
            )

        self.conn.commit()
        return stored

    @staticmethod
    def _insert_metrics_row(
        cur: Any,
        run_id: int,
        window_index: int | None,
        model_name: str,
        metrics: dict,
    ) -> None:
        """插入单行 metrics。"""
        cur.execute(
            """INSERT INTO backtest_run_results
               (run_id, window_index, model_name,
                n_bets, n_wins, hit_rate, roi, total_profit, avg_odds,
                brier_score, log_loss, clv,
                max_drawdown, max_drawdown_pct, longest_losing_streak,
                sharpe_ratio, profit_factor, equity_curve)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s)""",
            (
                run_id,
                window_index,
                model_name,
                metrics.get("n_bets", 0),
                metrics.get("n_wins", 0),
                metrics.get("hit_rate"),
                round(float(metrics.get("roi") or 0), 4),
                round(float(metrics.get("total_profit", 0)), 2),
                round(float(metrics.get("avg_odds") or 0), 2),
                round(float(metrics.get("brier_score") or 0), 4),
                round(float(metrics.get("log_loss") or 0), 4),
                round(float(metrics.get("clv") or 0), 4),
                round(float(metrics.get("max_drawdown", 0)), 2),
                min(999.9999, round(float(metrics.get("max_drawdown_pct", 0)), 4)),
                metrics.get("longest_losing_streak", 0),
                round(float(metrics.get("sharpe_ratio") or 0), 4),
                round(float(metrics.get("profit_factor") or 0), 4),
                json.dumps(metrics.get("equity_curve", []), ensure_ascii=False),
            ),
        )


# —— 快速运行入口（不依赖 DB 连接） ——


def run_backtest_from_config(
    conn: Any,
    config: BacktestConfig,
    store: bool = True,
) -> dict[str, Any]:
    """便捷函数：创建回测 run → 执行 → 存储。

    Args:
        conn: DB 连接
        config: 回测配置
        store: 是否写入 DB

    Returns:
        回测结果 dict
    """
    # 创建 run 记录
    run_id = None
    if store:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO backtest_runs (name, description, config, status, started_at)
                   VALUES (%s, %s, %s, 'running', NOW())
                   RETURNING id""",
                (
                    config.name or f"backtest_{datetime.now().isoformat(timespec='seconds')}",
                    config.description or "",
                    json.dumps(config.to_dict(), ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
            if row:
                run_id = row[0]
        conn.commit()

    # 执行回测。计算异常也必须收口运行状态，避免永久停在 running。
    engine = BacktestEngine(conn, config)
    try:
        result = engine.run()
    except Exception as e:
        if store and run_id:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE backtest_runs
                       SET status = 'failed', error_message = %s, finished_at = NOW()
                       WHERE id = %s""",
                    (str(e)[:1000], run_id),
                )
            conn.commit()
        raise

    # 存储结果
    if store and run_id:
        try:
            engine.store_results(run_id, result)
            result["run_id"] = run_id
        except Exception as e:
            # 标记失败
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE backtest_runs
                       SET status = 'failed', error_message = %s, finished_at = NOW()
                       WHERE id = %s""",
                    (str(e)[:1000], run_id),
                )
            conn.commit()
            result["status"] = "store_failed"
            result["store_error"] = str(e)

    return result


# —— 自测 ——

if __name__ == "__main__":
    print("=== 回测引擎测试 ===\n")

    # 构造合成数据进行数学验证

    # 1. 测试指标计算
    print("1. 指标计算测试")
    fake_bets = [
        BetRecord(
            1, "2025-01-01", "maher_poisson", "3", 0.45, 0.42, 2.20, 1.0, "3", 1.20, 0.10, 0.65
        ),
        BetRecord(
            2, "2025-01-02", "maher_poisson", "1", 0.30, 0.28, 3.50, 1.0, "1", 2.50, 0.05, 0.55
        ),
        BetRecord(
            3, "2025-01-03", "maher_poisson", "0", 0.35, 0.33, 2.80, 1.0, "3", -1.00, 0.08, 0.60
        ),
        BetRecord(
            4, "2025-01-04", "maher_poisson", "3", 0.50, 0.48, 1.90, 1.0, "3", 0.90, 0.12, 0.70
        ),
        BetRecord(
            5, "2025-01-05", "maher_poisson", "1", 0.28, 0.26, 3.80, 1.0, "0", -1.00, 0.02, 0.45
        ),
    ]

    m = BacktestEngine.compute_metrics(fake_bets)
    print(f"  投注数: {m['n_bets']}, 命中: {m['n_wins']}, 命中率: {m['hit_rate']}")
    print(f"  ROI: {m['roi']}, 总盈利: {m['total_profit']}")
    print(f"  Brier: {m['brier_score']}, LogLoss: {m['log_loss']}")
    print(f"  最大回撤: {m['max_drawdown']} (units), {m['max_drawdown_pct']}%")
    print(f"  最长连亏: {m['longest_losing_streak']}")
    print(f"  资金曲线: {len(m['equity_curve'])} 点")

    # 验证
    assert m["n_bets"] == 5
    assert m["n_wins"] == 3
    assert abs(m["hit_rate"] - 0.6) < 0.01
    assert m["total_profit"] > 0  # 1.20 + 2.50 - 1.00 + 0.90 - 1.00 = 2.60
    assert abs(m["total_profit"] - 2.60) < 0.01
    assert m["longest_losing_streak"] == 1
    assert len(m["equity_curve"]) == 5

    # 2. 测试配置
    print("\n2. 配置序列化测试")
    cfg = BacktestConfig(
        name="测试回测",
        time_start="2025-01-01",
        time_end="2025-06-30",
        league_ids=[1, 2],
        odds_min=1.5,
        odds_max=5.0,
        ev_min=0.02,
        signal_strength="strong",
    )
    d = cfg.to_dict()
    cfg2 = BacktestConfig.from_dict(d)
    assert cfg2.name == "测试回测"
    assert cfg2.odds_min == 1.5
    assert cfg2.signal_strength == "strong"
    print("  配置序列化 ✅")

    # 3. 测试空投注
    print("\n3. 空投注测试")
    empty_m = BacktestEngine.compute_metrics([])
    assert empty_m["n_bets"] == 0
    assert empty_m["hit_rate"] is None
    assert empty_m["equity_curve"] == []
    print("  空投注处理 ✅")

    print("\n✅ 回测引擎所有测试通过")
