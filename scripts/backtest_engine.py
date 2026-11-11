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
import logging
import math
import os
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

from scripts.market_metric_validation import (
    PROBABILITY_SUM_TOLERANCE,
    finite_number,
    probability_value,
)
from scripts.training_manifest import (
    RESULT_REVISION_VISIBILITY_CTE,
    CandidateMatch,
    _normalize_result_observation,
)

_LOG = logging.getLogger(__name__)

# Ensure project root on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# —— 数据结构 ——

CURRENT_METHODOLOGY_VERSION = 5
MAX_BACKTEST_DAYS = 36500
MAX_BACKTEST_WINDOWS = 1000


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

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """One contract for API, CLI, replay and mutable legacy callers."""
        for key in ("train_window_days", "test_window_days", "step_days"):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= MAX_BACKTEST_DAYS:
                raise ValueError(f"{key} 必须是 1–{MAX_BACKTEST_DAYS} 的整数")
        if type(self.walk_forward) is not bool:
            raise ValueError("walk_forward 必须是布尔值")
        dates: dict[str, date] = {}
        for key in ("time_start", "time_end"):
            value = getattr(self, key)
            if value is None:
                continue
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} 必须是有效的 YYYY-MM-DD 日期") from exc
            dates[key] = parsed
        if len(dates) == 2:
            span = (dates["time_end"] - dates["time_start"]).days
            if not 0 <= span <= MAX_BACKTEST_DAYS:
                raise ValueError(f"time_start/time_end 必须有序且跨度不超过 {MAX_BACKTEST_DAYS} 天")
            if self.walk_forward:
                count = max(0, (span - self.train_window_days - 1) // self.step_days + 1)
                if count > MAX_BACKTEST_WINDOWS:
                    raise ValueError(f"回测窗口超过 {MAX_BACKTEST_WINDOWS}，请增大 step_days")
        for key in ("league_ids", "risk_levels"):
            value = getattr(self, key)
            if value is not None and (not isinstance(value, list) or value):
                raise ValueError(f"{key} 暂不支持非空筛选，不能静默使用全量数据")
        for key in ("model_names", "play_types", "vote_directions", "model_ids"):
            value = getattr(self, key)
            if value is None:
                continue
            if not isinstance(value, list) or len(value) > 100:
                raise ValueError(f"{key} 必须是最多 100 项的列表")
            if key == "model_ids":
                valid = all(type(item) is int and item > 0 for item in value)
            else:
                valid = all(
                    isinstance(item, str) and item.strip() and len(item) <= 200 for item in value
                )
            if not valid:
                raise ValueError(f"{key} 包含无效项")
        if self.signal_strength not in ("strong", "weak", "all"):
            raise ValueError("signal_strength 必须是 strong、weak 或 all")
        for key, lower, upper, inclusive in (
            ("stake_per_bet", 0, 1e9, False),
            ("min_model_prob", 0, 1, True),
            ("confidence_min", 0, 1, True),
            ("odds_min", 1, 1e6, False),
            ("odds_max", 1, 1e6, False),
            ("ev_min", -1, 1e6, True),
            ("ev_max", -1, 1e6, True),
        ):
            value = getattr(self, key)
            if value is None and key not in ("stake_per_bet", "min_model_prob"):
                continue
            number = None if isinstance(value, str) else finite_number(value)
            if (
                number is None
                or number > upper
                or (number < lower if inclusive else number <= lower)
            ):
                raise ValueError(f"{key} 必须是合法范围内的有限数值")
        for lower_field, upper_field in (
            ("odds_min", "odds_max"),
            ("ev_min", "ev_max"),
        ):
            if getattr(self, lower_field) is not None and getattr(self, upper_field) is not None:
                if getattr(self, lower_field) > getattr(self, upper_field):
                    raise ValueError(f"{lower_field} 不能大于 {upper_field}")
        for key in ("name", "description"):
            limit = 255 if key == "name" else 5000
            if not isinstance(getattr(self, key), str) or len(getattr(self, key)) > limit:
                raise ValueError(f"{key} 必须是最多 {limit} 字符的文本")

    def to_dict(self) -> dict:
        return {
            # v5 排除不完整/负比分、矛盾SPF及非法数值；缺市场概率不补0。
            # 继续按玩法匹配官方赛果，
            # 采用同版本/时刻的赛前最新组与预测时点赔率；稀疏组不补齐。
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
    market_prob: float | None
    odds: float  # 赔率 (sp_value)
    stake: float
    actual_result: str  # "3" / "1" / "0"
    profit: float  # 盈亏 (正=赢, 负=输)
    ev: float
    confidence: float | None
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


@dataclass(frozen=True)
class ResearchMatch:
    """One bounded, materialized official match and its prediction-time market."""

    candidate: CandidateMatch
    business_date: date
    prediction_as_of: datetime
    odds_by_option: Mapping[str, float]
    odds_snapshot_times: Mapping[str, datetime | str]
    odds_snapshot_ids: Mapping[str, int] = field(default_factory=dict)
    result_status: str = "final"
    team_identity: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    competition_season_id: int | None = None


@dataclass(frozen=True)
class ResearchEvaluationConfig:
    """Resource and chronology limits for offline P106-04 evaluation."""

    fold_count: int = 3
    test_window_days: int = 30
    holdout_days: int = 30
    predeclared_final_window_start: date | None = None
    predeclared_final_window_end: date | None = None
    min_team_matches: int = 5
    prediction_lead_minutes: int = 60
    competition_season_id: int | None = None
    max_matches: int = 5000
    max_report_bytes: int = 5_000_000


@dataclass(frozen=True)
class ResearchTimeSplit:
    index: int | None
    test_start: date
    test_end: date
    final_holdout: bool = False


class _ResearchDatedItem(Protocol):
    @property
    def business_date(self) -> date: ...


def _has_finalized_research_result(row: _ResearchDatedItem) -> bool:
    """Require a final result identity and score for materialized match rows."""
    if not hasattr(row, "result_status"):
        return True
    if cast(Any, row).result_status not in {"final", "confirmed"}:
        return False

    candidate = getattr(row, "candidate", None)
    if candidate is None:
        return False
    result_id = getattr(candidate, "result_id", None)
    home_goals = getattr(candidate, "home_goals", None)
    away_goals = getattr(candidate, "away_goals", None)
    if (
        type(result_id) is not int
        or result_id <= 0
        or type(home_goals) is not int
        or home_goals < 0
        or type(away_goals) is not int
        or away_goals < 0
    ):
        return False
    return True


def _has_complete_research_label_receipt(row: _ResearchDatedItem) -> bool:
    """Verify the exact terminal score has a source-observation receipt.

    Date-only rows without a match status are upstream-prevalidated. Materialized
    research matches must carry the matching P104 value revision and its
    first-acquired/available timestamps.
    """
    if not hasattr(row, "result_status"):
        return True
    candidate = getattr(row, "candidate", None)
    if candidate is None:
        return False
    result_id = getattr(candidate, "result_id", None)
    home_goals = getattr(candidate, "home_goals", None)
    away_goals = getattr(candidate, "away_goals", None)
    observations = getattr(candidate, "label_observations", ())
    if not isinstance(observations, Sequence) or isinstance(observations, str | bytes):
        return False
    for observation in observations:
        try:
            normalized = _normalize_result_observation(observation)
        except TypeError, ValueError:
            continue
        if (
            normalized.result_id == result_id
            and normalized.fact_status == "value"
            and normalized.home_goals == home_goals
            and normalized.away_goals == away_goals
        ):
            return True
    return False


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
        config.validate()
        self.conn = conn
        self.config = config

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _build_query(self) -> tuple[str, list]:
        """构建回测数据查询 SQL。

        JOIN: model_predictions → model_versions → official_matches → official_results → official_odds_snapshots
        """
        self.config.validate()
        from scripts.model_evaluation_scope import (
            EVALUATION_PREDICTION_ROWS_CTES,
            SETTLED_SPF_RESULTS_CTE,
        )

        where = [
            "mp.prediction_rank = 1",
            "m.match_status = 'Settled'",
            "r.full_home_goals >= 0",
            "r.full_away_goals >= 0",
            "(mp.play_type <> 'spf' OR "
            "(spf.match_id IS NOT NULL AND mp.option_code IN ('3', '1', '0')))",
            "mp.model_probability > 0",
        ]
        params: list = []

        if self.config.time_start:
            where.append("m.business_date >= %s")
            params.append(self.config.time_start)
        if self.config.time_end:
            where.append("m.business_date <= %s")
            params.append(self.config.time_end)
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

        where_clause = " AND ".join(where)

        sql = f"""{EVALUATION_PREDICTION_ROWS_CTES}{SETTLED_SPF_RESULTS_CTE}
            , eligible_predictions AS (
                SELECT
                    source_mp.*,
                    source_mv.model_name AS canonical_model_name
                FROM evaluation_prediction_rows source_mp
                JOIN official_matches source_m ON source_m.id = source_mp.match_id
                JOIN model_versions source_mv ON source_mv.id = source_mp.model_version_id
                WHERE source_mp.predict_time < source_m.kickoff_time
                  AND source_mp.validation_status = 'valid'
                  AND (source_mp.play_type <> 'spf' OR source_mp.option_code IN ('3', '1', '0'))
                  AND COALESCE(
                      (source_mp.uncertainty_reason->>'model_independent')::boolean,
                      false
                  ) = true
            ), prediction_groups AS (
                -- Inspect every present option before numeric/confidence/EV
                -- filters can disguise a malformed full group as a sparse one.
                SELECT match_id, canonical_model_name, model_version_id, play_type, predict_time,
                       MAX(id) AS latest_prediction_id,
                       BOOL_AND(COALESCE(model_probability BETWEEN 0 AND 1, false))
                           AND CASE WHEN COUNT(*) = 3
                               THEN ABS(SUM(model_probability) - 1) <= {PROBABILITY_SUM_TOLERANCE}
                               ELSE SUM(model_probability) <= 1 + {PROBABILITY_SUM_TOLERANCE}
                           END AS model_group_valid,
                       BOOL_AND(COALESCE(market_probability BETWEEN 0 AND 1, false))
                           AND CASE WHEN COUNT(*) = 3
                               THEN ABS(SUM(market_probability) - 1) <= {PROBABILITY_SUM_TOLERANCE}
                               ELSE SUM(market_probability) <= 1 + {PROBABILITY_SUM_TOLERANCE}
                           END AS market_group_valid
                FROM eligible_predictions
                GROUP BY match_id, canonical_model_name, model_version_id, play_type, predict_time
            ), ranked_prediction_groups AS (
                -- Select the newest version/time as one unit. Never borrow
                -- older-version peers or fall back after rejecting its values.
                SELECT prediction_groups.*,
                       DENSE_RANK() OVER (
                           PARTITION BY match_id, canonical_model_name, play_type
                           ORDER BY predict_time DESC, latest_prediction_id DESC
                       ) AS prediction_rank
                FROM prediction_groups
            ), ranked_predictions AS (
                SELECT source_mp.*, groups.prediction_rank, groups.market_group_valid
                FROM eligible_predictions source_mp
                JOIN ranked_prediction_groups groups
                  ON groups.match_id = source_mp.match_id
                 AND groups.model_version_id = source_mp.model_version_id
                 AND groups.play_type = source_mp.play_type
                 AND groups.predict_time = source_mp.predict_time
                WHERE source_mp.play_type <> 'spf' OR groups.model_group_valid
            )
            SELECT
                mp.match_id,
                m.business_date AS match_date,
                mv.model_name,
                mp.play_type,
                mp.option_code,
                mp.model_probability,
                CASE WHEN mp.play_type = 'spf' AND NOT mp.market_group_valid THEN NULL
                     ELSE mp.market_probability END AS market_probability,
                mp.ev,
                mp.confidence_score,
                mp.predict_time,
                CASE
                    WHEN mp.play_type = 'spf' THEN spf.actual_result
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
            LEFT JOIN settled_spf_results spf ON spf.match_id = mp.match_id
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
        self.config.validate()
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

        # Bound work before allocating windows. Ordinals avoid date.max overflow.
        last_start = max_date.toordinal() - cfg.train_window_days - 1
        count = max(0, (last_start - min_date.toordinal()) // cfg.step_days + 1)
        if count > MAX_BACKTEST_WINDOWS:
            raise ValueError(
                f"回测窗口超过 {MAX_BACKTEST_WINDOWS}，请增大 step_days 或缩小日期范围"
            )
        windows = []
        current = min_date
        idx = 0

        while current < max_date:
            train_start = current
            test_ordinal = current.toordinal() + cfg.train_window_days + 1
            if test_ordinal > max_date.toordinal():
                break
            train_end = date.fromordinal(test_ordinal - 1)
            test_start = date.fromordinal(test_ordinal)
            test_end = date.fromordinal(
                min(test_ordinal + cfg.test_window_days, max_date.toordinal())
            )

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
            next_ordinal = current.toordinal() + cfg.step_days
            if next_ordinal >= max_date.toordinal():
                break
            current = date.fromordinal(next_ordinal)

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
        mp = probability_value(row.get("model_probability"))
        if mp is None or mp <= 0 or mp < cfg.min_model_prob:
            return False

        # Explicit confidence filters must also hold for in-memory/replayed rows.
        # PostgreSQL NUMERIC NaN sorts above finite values and can pass SQL >=.
        if cfg.confidence_min is not None:
            confidence = probability_value(row.get("confidence_score"))
            if confidence is None or confidence < cfg.confidence_min:
                return False

        # 信号强度过滤
        if cfg.signal_strength != "all":
            direction = "strong" if mp > 0.40 else ("weak" if mp > 0.30 else "against")
            if direction != cfg.signal_strength:
                return False

        # 赔率过滤
        sp = finite_number(row.get("sp_value"))
        if sp is None or sp <= 1:
            return False
        if cfg.odds_min is not None and sp < cfg.odds_min:
            return False
        if cfg.odds_max is not None and sp > cfg.odds_max:
            return False

        # EV 过滤
        ev = finite_number(row.get("ev"))
        if ev is None:
            return False
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
                    market_prob=probability_value(row.get("market_probability")),
                    odds=sp,
                    stake=stake,
                    actual_result=actual,
                    profit=profit,
                    ev=float(row.get("ev", 0)),
                    confidence=finite_number(row.get("confidence_score")),
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
                "probability_edge": None,
                "odds_clv": None,
                "clv_semantics": "probability_edge_legacy_alias",
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
        probability_edge_total = 0.0
        complete_market = True
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
            # Probability edge at prediction time; closing odds are not available.
            market_probability = probability_value(b.market_prob)
            if market_probability is None:
                complete_market = False
            else:
                probability_edge_total += b.model_prob - market_probability

        brier_score = brier_total / n
        log_loss = log_loss_total / n
        # Do not turn missing market evidence into zero or silently change
        # the aggregate denominator. Profit and quality remain independent.
        probability_edge = probability_edge_total / n if complete_market else None

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
            "clv": round(probability_edge, 4) if probability_edge is not None else None,
            "probability_edge": round(probability_edge, 4)
            if probability_edge is not None
            else None,
            "odds_clv": None,
            "clv_semantics": "probability_edge_legacy_alias",
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
                all_bets_by_key[
                    (
                        bet.match_id,
                        bet.model_name,
                        bet.play_type,
                        bet.match_date,
                    )
                ] = bet

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
            n_test = len({r["match_id"] for r in rows if ts <= str(r["match_date"])[:10] <= te})

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
                   WHERE id = %s AND status = 'running'""",
                (run_id,),
            )
            if cur.rowcount != 1:
                raise RuntimeError("backtest run is no longer running")

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


def _record_backtest_failure(conn: Any, run_id: int, error: Exception) -> bool:
    """Discard aborted/partial result writes; never overwrite a committed success."""
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE backtest_runs
               SET status = 'failed', error_message = %s, finished_at = clock_timestamp()
               WHERE id = %s AND status = 'running' RETURNING id""",
            (str(error)[:1000], run_id),
        )
        changed = cur.fetchone() is not None
    conn.commit()
    return changed


def run_backtest_from_config(
    conn: Any,
    config: BacktestConfig,
    store: bool = True,
    *,
    ai_job_run_id: int | None = None,
) -> dict[str, Any]:
    """便捷函数：创建回测 run → 执行 → 存储。

    Args:
        conn: DB 连接
        config: 回测配置
        store: 是否写入 DB

    Returns:
        回测结果 dict
    """
    config.validate()  # Reject invalid mutable configurations before any business write.
    # 创建 run 记录
    run_id = None
    if store:
        with conn.cursor() as cur:
            values = (
                config.name or f"backtest_{datetime.now().isoformat(timespec='seconds')}",
                config.description or "",
                json.dumps(config.to_dict(), ensure_ascii=False),
            )
            if ai_job_run_id is None:
                # Isolated research/legacy callers retain their unlinked schema
                # contract. Scheduler/manual API always pass an explicit owner.
                cur.execute(
                    """INSERT INTO backtest_runs (name, description, config, status, started_at)
                       VALUES (%s, %s, %s, 'running', NOW()) RETURNING id""",
                    values,
                )
            else:
                from scripts.backtest_job_execution import EXECUTION_PROTOCOL

                cur.execute(
                    """INSERT INTO backtest_runs
                         (name, description, config, status, started_at, ai_job_run_id)
                       SELECT %s, %s, %s, 'running', NOW(), id FROM ai_job_runs
                       WHERE id=%s AND job_code='backtest' AND status='running'
                         AND input_snapshot_refs->>'execution_protocol'=%s RETURNING id""",
                    (*values, ai_job_run_id, EXECUTION_PROTOCOL),
                )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("backtest run could not be created for its audit owner")
            run_id = row[0]
        conn.commit()

    # 执行回测。计算异常也必须收口运行状态，避免永久停在 running。
    engine = BacktestEngine(conn, config)
    try:
        result = engine.run()
    except Exception as e:
        if store and run_id:
            try:
                _record_backtest_failure(conn, run_id, e)
            except Exception:
                _LOG.exception("Failed to persist backtest computation failure")
        raise

    # 存储结果
    if store and run_id:
        result["run_id"] = run_id
        try:
            engine.store_results(run_id, result)
        except Exception as e:
            try:
                changed = _record_backtest_failure(conn, run_id, e)
            except Exception as cleanup_error:
                _LOG.exception("Failed to reconcile backtest result storage")
                raise e from cleanup_error
            if not changed:
                # COMMIT may have succeeded despite a lost acknowledgement.
                # Let the owner read the durable completed fact; do not claim a
                # storage failure or reclassify the already committed output.
                raise
            result["status"] = "store_failed"
            result["store_error"] = str(e)

    return result


# —— P106-04: isolated time-split research evaluation ——


def _validate_research_config(config: ResearchEvaluationConfig) -> None:
    if not isinstance(config, ResearchEvaluationConfig):
        raise TypeError("config must be a ResearchEvaluationConfig")
    if not 1 <= config.fold_count <= 5:
        raise ValueError("fold_count must be between 1 and 5")
    if not 1 <= config.test_window_days <= 90:
        raise ValueError("test_window_days must be between 1 and 90")
    if not 1 <= config.holdout_days <= 90:
        raise ValueError("holdout_days must be between 1 and 90")
    window_start = config.predeclared_final_window_start
    window_end = config.predeclared_final_window_end
    if (window_start is None) != (window_end is None):
        raise ValueError("predeclared final window requires both start and end dates")
    if window_start is not None and window_end is not None:
        if type(window_start) is not date or type(window_end) is not date:
            raise ValueError("predeclared final window boundaries must be dates")
        if window_end < window_start:
            raise ValueError("predeclared final window end must not precede start")
        if (window_end - window_start).days + 1 != config.holdout_days:
            raise ValueError("predeclared final window length must equal holdout_days")
    if config.min_team_matches < 1:
        raise ValueError("min_team_matches must be positive")
    if not 1 <= config.prediction_lead_minutes <= 10080:
        raise ValueError("prediction_lead_minutes must be between 1 and 10080")
    if config.competition_season_id is not None and (
        type(config.competition_season_id) is not int or config.competition_season_id <= 0
    ):
        raise ValueError("competition_season_id must be a positive integer")
    if not 1 <= config.max_matches <= 5000:
        raise ValueError("max_matches must be between 1 and 5000")
    if not 1024 <= config.max_report_bytes <= 5_000_000:
        raise ValueError("max_report_bytes must be between 1024 and 5000000")


def build_research_time_splits(
    matches: Sequence[_ResearchDatedItem],
    config: ResearchEvaluationConfig | None = None,
) -> list[ResearchTimeSplit]:
    """Build non-overlapping windows from final matches or prevalidated date-only labels."""
    config = config or ResearchEvaluationConfig()
    _validate_research_config(config)
    if not matches:
        raise ValueError("research evaluation requires materialized matches")
    dates = sorted({row.business_date for row in matches if _has_finalized_research_result(row)})
    if not dates:
        raise ValueError("research evaluation requires finalized target results")
    latest_date = dates[-1]
    predeclared_start = config.predeclared_final_window_start
    predeclared_end = config.predeclared_final_window_end
    if predeclared_start is not None and predeclared_end is not None:
        has_predeclared_final_window = True
        holdout_start = predeclared_start
        holdout_end = predeclared_end
        window_items = [row for row in matches if holdout_start <= row.business_date <= holdout_end]
        if not window_items:
            raise ValueError("predeclared final window contains no target matches")
        if any(
            not _has_finalized_research_result(row) or not _has_complete_research_label_receipt(row)
            for row in window_items
        ):
            raise ValueError("predeclared final window contains unresolved results")
        if not any(row.business_date == holdout_end for row in window_items):
            raise ValueError("predeclared final window end must be a match date")
    else:
        has_predeclared_final_window = False
        holdout_end = latest_date
        holdout_start = latest_date - timedelta(days=config.holdout_days - 1)
    splits: list[ResearchTimeSplit] = []
    first_test_start: date | None = None

    for index in range(config.fold_count):
        days_before_holdout = 1 + (config.fold_count - index - 1) * config.test_window_days
        test_end = holdout_start - timedelta(days=days_before_holdout)
        test_start = test_end - timedelta(days=config.test_window_days - 1)
        first_test_start = test_start if first_test_start is None else first_test_start
        splits.append(
            ResearchTimeSplit(
                index=index,
                test_start=test_start,
                test_end=test_end,
            )
        )

    if first_test_start is None or dates[0] >= first_test_start:
        raise ValueError("materialized history does not precede the first test window")
    splits.append(
        ResearchTimeSplit(
            index=None,
            test_start=holdout_start,
            test_end=holdout_end,
            final_holdout=has_predeclared_final_window,
        )
    )
    if any(
        left.test_end >= right.test_start for left, right in zip(splits, splits[1:], strict=False)
    ):
        raise ValueError("research test windows overlap")
    return splits


def _research_datetime(value: datetime | str) -> datetime:
    normalized = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(normalized, datetime):
        raise TypeError("research timestamps must be datetimes")
    if normalized.tzinfo is not None and normalized.utcoffset() is not None:
        raise ValueError("research timestamps must use the naive Beijing DB convention")
    return normalized


def _research_source_snapshot(matches: Sequence[ResearchMatch]) -> str:
    from scripts.model_prediction_run_identity import content_sha256

    snapshot = []
    for row in sorted(matches, key=lambda item: (item.business_date, item.candidate.match_id)):
        candidate = row.candidate
        snapshot.append(
            {
                "match_id": candidate.match_id,
                "result_id": candidate.result_id,
                "business_date": row.business_date.isoformat(),
                "competition_season_id": row.competition_season_id,
                "kickoff_at": _research_datetime(candidate.kickoff_at).isoformat(),
                "official_publish_time": (
                    _research_datetime(candidate.official_publish_time).isoformat()
                    if candidate.official_publish_time is not None
                    else None
                ),
                "home_team_id": candidate.home_team_id,
                "away_team_id": candidate.away_team_id,
                "team_identity": row.team_identity,
                "home_goals": candidate.home_goals,
                "away_goals": candidate.away_goals,
                "match_status": candidate.match_status,
                "result_status": row.result_status,
                "result_observations": [
                    {
                        "revision_id": observation.revision_id,
                        "result_id": observation.result_id,
                        "fact_status": observation.fact_status,
                        "home_goals": observation.home_goals,
                        "away_goals": observation.away_goals,
                        "published_at": (
                            observation.published_at.isoformat(timespec="microseconds")
                            if observation.published_at is not None
                            else None
                        ),
                        "first_acquired_at": observation.first_acquired_at.isoformat(
                            timespec="microseconds"
                        ),
                        "available_at": observation.available_at.isoformat(timespec="microseconds"),
                    }
                    for observation in (
                        _normalize_result_observation(item) for item in candidate.label_observations
                    )
                ],
                "prediction_as_of": _research_datetime(row.prediction_as_of).isoformat(),
                "odds_by_option": dict(sorted(row.odds_by_option.items())),
                "odds_snapshot_times": {
                    option: _research_datetime(timestamp).isoformat()
                    for option, timestamp in sorted(row.odds_snapshot_times.items())
                },
                "odds_snapshot_ids": dict(sorted(row.odds_snapshot_ids.items())),
            }
        )
    return content_sha256(snapshot)


def _research_code_fingerprint() -> dict[str, Any]:
    from scripts.model_prediction_run_identity import fingerprint_runtime_sources

    return fingerprint_runtime_sources(
        Path(_PROJECT_ROOT),
        (
            "scripts/backtest_engine.py",
            "scripts/mle_trainer.py",
            "scripts/training_manifest.py",
            "scripts/model_artifact_identity.py",
            "scripts/maher_goal_rate_runtime.py",
            "scripts/poisson_model.py",
            "scripts/evaluation_metrics.py",
            "scripts/odds_conversion.py",
        ),
    )


def _research_actual(candidate: CandidateMatch) -> str | None:
    if candidate.home_goals is None or candidate.away_goals is None:
        return None
    if candidate.home_goals > candidate.away_goals:
        return "3"
    if candidate.home_goals == candidate.away_goals:
        return "1"
    return "0"


def _research_market_probabilities(row: ResearchMatch) -> dict[str, float] | None:
    from scripts.odds_conversion import normalize_probabilities

    if set(row.odds_by_option) != {"3", "1", "0"}:
        return None
    if set(row.odds_snapshot_times) != {"3", "1", "0"}:
        return None
    if set(row.odds_snapshot_ids) != {"3", "1", "0"}:
        raise ValueError("market_snapshot_identity_missing")
    as_of = _research_datetime(row.prediction_as_of)
    snapshot_times = {
        option: _research_datetime(timestamp)
        for option, timestamp in row.odds_snapshot_times.items()
    }
    if any(timestamp > as_of for timestamp in snapshot_times.values()):
        raise ValueError("odds_snapshot_after_prediction_as_of")
    odds = {option: float(row.odds_by_option[option]) for option in ("3", "1", "0")}
    if any(not math.isfinite(value) or value <= 1 for value in odds.values()):
        raise ValueError("invalid_market_odds")
    try:
        probabilities = normalize_probabilities(odds)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("invalid_market_odds") from exc
    return {option: probabilities[option] for option in ("3", "1", "0")}


def _research_prediction_probabilities(
    fitted_parameters: Mapping[str, Any],
    home_team_id: int,
    away_team_id: int,
) -> dict[str, float] | None:
    from scripts.maher_goal_rate_runtime import load_trained_goal_rates
    from scripts.poisson_model import derive_1x2, score_matrix

    if fitted_parameters.get("converged") is not True:
        return None
    normalized = dict(fitted_parameters)
    for name in ("attack", "defense", "team_match_counts"):
        values = fitted_parameters.get(name)
        if not isinstance(values, Mapping):
            return None
        normalized[name] = {str(key): value for key, value in values.items()}
    rates = load_trained_goal_rates(
        {"maher_poisson": normalized},
        {"home_team_id": home_team_id, "away_team_id": away_team_id},
    )
    if rates is None:
        return None
    return derive_1x2(score_matrix(rates.home_lambda, rates.away_lambda))


def _research_metric_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"sample_count": len(rows)}
    for name in ("brier_score", "log_loss", "rps"):
        values = [float(row[name]) for row in rows if row.get(name) is not None]
        metrics[name] = round(math.fsum(values) / len(values), 8) if values else None
    return metrics


def _research_paired_metric_comparison(
    predictions: Sequence[Mapping[str, Any]],
    *,
    left_name: str = "model",
    right_name: str = "market_baseline",
    predeclared_window: bool = False,
) -> dict[str, Any]:
    """Return paired point estimates and an optional fixed-window research bound.

    No bootstrap percentile interval is emitted because cross-date serial
    dependence is not modeled. The optional Azuma-Hoeffding result is restricted
    to a predeclared single window, targets the date-conditional expected Brier
    delta, and is never decision or promotion evidence.
    """
    if type(predeclared_window) is not bool:
        raise ValueError("predeclared_window must be a boolean attestation")
    metric_names = ("brier_score", "log_loss", "rps")
    rows: list[tuple[str, str, dict[str, float]]] = []
    seen_match_ids: set[str] = set()
    for prediction in predictions:
        match_id = prediction.get("match_id")
        match_key = str(match_id) if match_id is not None else ""
        if not match_key or match_key in seen_match_ids:
            raise ValueError("paired research predictions require unique match IDs")
        seen_match_ids.add(match_key)

        raw_date = prediction.get("business_date")
        try:
            if isinstance(raw_date, datetime):
                raise ValueError
            elif isinstance(raw_date, date):
                business_date = raw_date.isoformat()
            elif isinstance(raw_date, str):
                business_date = date.fromisoformat(raw_date).isoformat()
            else:
                raise ValueError
        except ValueError as exc:
            raise ValueError("paired research predictions require an ISO business date") from exc

        metrics = prediction.get("metrics")
        left = metrics.get(left_name) if isinstance(metrics, Mapping) else None
        right = metrics.get(right_name) if isinstance(metrics, Mapping) else None
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ValueError("paired research prediction is missing one side of the comparison")
        deltas: dict[str, float] = {}
        for name in metric_names:
            left_value = left.get(name)
            right_value = right.get(name)
            if (
                isinstance(left_value, bool)
                or isinstance(right_value, bool)
                or not isinstance(left_value, int | float)
                or not isinstance(right_value, int | float)
                or not math.isfinite(float(left_value))
                or not math.isfinite(float(right_value))
            ):
                raise ValueError(f"paired research metric {name} is missing or non-finite")
            deltas[name] = float(left_value) - float(right_value)
        rows.append((business_date, match_key, deltas))

    ordered_rows = sorted(rows, key=lambda row: (row[0], row[1]))
    block_dates = sorted({business_date for business_date, _, _ in ordered_rows})
    sample_count = len(rows)
    block_count = len(block_dates)
    if not sample_count:
        status = "no_paired_observations"
    elif block_count < 2:
        status = "insufficient_date_clusters"
    else:
        status = "descriptive_only"

    result: dict[str, Any] = {
        "status": status,
        "comparison": f"{left_name}_minus_{right_name}",
        "method": "paired_mean_by_business_date/v1",
        "interval_status": "not_computed_serial_dependence_not_modeled",
        "interval_semantics": "paired_point_estimates_only",
        "target_estimate": "match_weighted_mean_paired_metric_delta",
        "sample_count": sample_count,
        "business_date_cluster_count": block_count,
        "serial_dependence_accounted_for": False,
        "decision_eligible": False,
        "promotion_eligible": False,
        "fixed_horizon_brier_bound": (
            _research_fixed_window_brier_bound(
                [(business_date, deltas["brier_score"]) for business_date, _, deltas in rows]
            )
            if predeclared_window
            else {
                "status": "not_computed_window_not_predeclared",
                "method": "date_cluster_azuma_hoeffding/v1",
                "confidence_level": 0.95,
                "sample_count": sample_count,
                "decision_eligible": False,
                "promotion_eligible": False,
            }
        ),
        "metrics": {},
    }
    means = {
        name: math.fsum(deltas[name] for _, _, deltas in ordered_rows) / sample_count
        if sample_count
        else None
        for name in metric_names
    }
    result["metrics"] = {}
    for name in metric_names:
        mean_delta = means[name]
        result["metrics"][name] = {
            "mean_delta": round(mean_delta, 8) if mean_delta is not None else None,
        }
    return result


def _research_fixed_window_brier_bound(
    dated_deltas: Sequence[tuple[date | str, float]], *, alpha: float = 0.05
) -> dict[str, Any]:
    """Bound one predeclared window's mean conditional Brier effect.

    The multiclass Brier score used here is in [0, 2], so a paired difference
    lies in [-2, 2]. Each business date is treated as one martingale increment;
    all matches on that date may depend arbitrarily on one another. Across
    dates the conditional means may change arbitrarily. The Azuma-Hoeffding
    radius therefore uses each date's full range, not an iid or stationarity
    estimate. Its target is the match-weighted conditional expected mean loss
    difference in one fixed evaluation window: each date's conditional expected
    loss sum is divided by the total match count, not averaged equally by date.
    """
    if isinstance(alpha, bool) or not isinstance(alpha, int | float):
        raise ValueError("alpha must be a finite number in (0, 1)")
    alpha = float(alpha)
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be a finite number in (0, 1)")

    grouped: dict[str, list[float]] = defaultdict(list)
    for raw_date, raw_delta in dated_deltas:
        try:
            if isinstance(raw_date, datetime):
                raise ValueError
            if isinstance(raw_date, date):
                business_date = raw_date.isoformat()
            elif isinstance(raw_date, str):
                business_date = date.fromisoformat(raw_date).isoformat()
            else:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Brier bound requires ISO business dates") from exc
        if (
            isinstance(raw_delta, bool)
            or not isinstance(raw_delta, int | float)
            or not math.isfinite(float(raw_delta))
            or not -2 <= float(raw_delta) <= 2
        ):
            raise ValueError("paired Brier differences must be finite and in [-2, 2]")
        grouped[business_date].append(float(raw_delta))

    sample_count = sum(len(values) for values in grouped.values())
    date_count = len(grouped)
    if sample_count == 0:
        return {
            "status": "no_paired_observations",
            "method": "date_cluster_azuma_hoeffding/v1",
            "interpretation": "conditional_expected_mean_brier_delta_research_only",
            "predeclared_window_attestation": "caller_supplied",
            "pair_eligibility_verified_by_function": False,
            "confidence_level": round(1 - alpha, 8),
            "sample_count": 0,
            "date_cluster_count": 0,
            "effective_date_cluster_count": 0.0,
            "mean_delta": None,
            "radius": None,
            "lower": None,
            "upper": None,
            "decision_eligible": False,
            "promotion_eligible": False,
        }

    cluster_sizes = [len(grouped[business_date]) for business_date in sorted(grouped)]
    squared_cluster_size_sum = sum(size * size for size in cluster_sizes)
    mean_delta = (
        math.fsum(math.fsum(grouped[business_date]) for business_date in sorted(grouped))
        / sample_count
    )
    sum_squared_ranges = 16 * squared_cluster_size_sum
    radius = math.sqrt(math.log(2 / alpha) * sum_squared_ranges / (2 * sample_count * sample_count))
    return {
        "status": "computed_fixed_horizon",
        "method": "date_cluster_azuma_hoeffding/v1",
        "interpretation": "conditional_expected_mean_brier_delta_research_only",
        "predeclared_window_attestation": "caller_supplied",
        "pair_eligibility_verified_by_function": False,
        "confidence_level": round(1 - alpha, 8),
        "target": "match_weighted_mean_date_conditional_expected_brier_delta_in_fixed_window",
        "window_assumption": "predeclared_single_final_look_and_pre_outcome_pair_eligibility",
        "dependence_assumption": "arbitrary_within_and_between_dates_via_martingale_differences",
        "sample_count": sample_count,
        "date_cluster_count": date_count,
        "effective_date_cluster_count": round(
            sample_count * sample_count / squared_cluster_size_sum, 8
        ),
        "mean_delta": round(mean_delta, 8),
        "radius": round(radius, 8),
        "lower": round(max(-2.0, mean_delta - radius), 8),
        "upper": round(min(2.0, mean_delta + radius), 8),
        "decision_eligible": False,
        "promotion_eligible": False,
    }


def _evaluate_research_window(
    matches: Sequence[ResearchMatch],
    split: ResearchTimeSplit,
    config: ResearchEvaluationConfig,
    code_fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    from scripts.evaluation_metrics import compute_match_metrics
    from scripts.mle_trainer import fit_maher_poisson_dataset
    from scripts.model_artifact_identity import attach_artifact_identity
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.training_manifest import build_training_dataset

    cutoff_at = datetime.combine(split.test_start, time.min) - timedelta(microseconds=1)
    dataset = build_training_dataset(
        (row.candidate for row in matches),
        min_matches=config.min_team_matches,
        cutoff_at=cutoff_at,
    )
    manifest = dataset.manifest.to_dict()
    fit_match_ids = [sample.match_id for sample in dataset.samples]
    manifest_match_ids = [sample.match_id for sample in dataset.manifest.included]
    if fit_match_ids != manifest_match_ids:
        raise ValueError("training manifest and Maher fit inputs differ")

    training_excluded: list[dict[str, Any]] = [
        {"match_id": sample.match_id, "reason": sample.reason}
        for sample in dataset.manifest.excluded
    ]
    training_excluded.sort(key=lambda sample: (sample["match_id"], sample["reason"]))
    training_excluded_counts: dict[str, int] = {}
    for sample in training_excluded:
        training_excluded_counts[sample["reason"]] = (
            training_excluded_counts.get(sample["reason"], 0) + 1
        )

    fitted: dict[str, Any] | None = None
    fit_failure: str | None = None
    if not dataset.samples:
        fit_failure = "no_source_observed_training_labels_before_cutoff"
    else:
        fit_result = fit_maher_poisson_dataset(dataset)
        if "error" in fit_result:
            fit_failure = str(fit_result["error"])
        elif fit_result.get("converged") is not True:
            fit_failure = "Maher-SPF fold fit did not converge"
        else:
            fitted = fit_result
    artifact_identity: Mapping[str, Any] | None = None
    if fitted is not None:
        artifact_parameters = {
            key: value
            for key, value in fitted.items()
            if key not in {"training_manifest", "training_start_date", "training_end_date"}
        }
        artifact = attach_artifact_identity(artifact_parameters, manifest)
        artifact_identity = artifact["_artifact_identity"]

    model_metrics: list[dict[str, Any]] = []
    market_metrics: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    scoped_matches = [
        row for row in matches if split.test_start <= row.business_date <= split.test_end
    ]
    if split.final_holdout and any(
        not _has_finalized_research_result(row) or not _has_complete_research_label_receipt(row)
        for row in scoped_matches
    ):
        raise ValueError("predeclared final window contains unresolved results")
    for row in sorted(scoped_matches, key=lambda item: item.candidate.match_id):
        candidate = row.candidate
        actual = _research_actual(candidate)
        reason: str | None = None
        market: dict[str, float] | None = None
        model: dict[str, float] | None = None
        if row.result_status not in {"final", "confirmed"}:
            reason = "official_result_not_final"
        elif candidate.home_team_id is None or candidate.away_team_id is None:
            ambiguous_side = next(
                (
                    side
                    for side in ("home", "away")
                    if row.team_identity.get(side, {}).get("name_match_count", 0) > 1
                ),
                None,
            )
            reason = "team_identity_ambiguous" if ambiguous_side else "team_unmapped"
        elif actual is None:
            reason = "official_score_missing"
        elif _research_datetime(row.prediction_as_of) >= _research_datetime(candidate.kickoff_at):
            reason = "prediction_as_of_not_before_kickoff"
        elif _research_datetime(row.prediction_as_of) != (
            _research_datetime(candidate.kickoff_at)
            - timedelta(minutes=config.prediction_lead_minutes)
        ):
            reason = "prediction_as_of_does_not_match_config"
        else:
            try:
                market = _research_market_probabilities(row)
            except ValueError as exc:
                reason = str(exc)
                market = None
            if reason is None and market is None:
                reason = "incomplete_market_vector"
        if reason is None:
            if fitted is None:
                reason = "training_model_not_evaluable"
            else:
                assert candidate.home_team_id is not None
                assert candidate.away_team_id is not None
                model = _research_prediction_probabilities(
                    fitted, candidate.home_team_id, candidate.away_team_id
                )
                if model is None:
                    reason = "team_history_or_model_rate_unavailable"
        if reason is not None:
            exclusion = {"match_id": candidate.match_id, "reason": reason}
            if row.team_identity:
                exclusion["team_identity"] = row.team_identity
            excluded.append(exclusion)
            continue

        assert actual is not None
        assert market is not None
        assert model is not None

        model_metric = compute_match_metrics(model, market, actual, "maher_poisson")
        market_metric = compute_match_metrics(market, market, actual, "market_baseline")
        model_row = {name: model_metric[name] for name in ("brier_score", "log_loss", "rps")}
        market_row = {name: market_metric[name] for name in ("brier_score", "log_loss", "rps")}
        model_metrics.append(model_row)
        market_metrics.append(market_row)
        predictions.append(
            {
                "match_id": candidate.match_id,
                "business_date": row.business_date.isoformat(),
                "competition_season_id": row.competition_season_id,
                "play_type": "spf",
                "prediction_as_of": _research_datetime(row.prediction_as_of).isoformat(),
                "actual_result": actual,
                "model_probabilities": model,
                "market_probabilities": market,
                "odds_by_option": dict(sorted(row.odds_by_option.items())),
                "odds_snapshot_times": {
                    option: _research_datetime(timestamp).isoformat()
                    for option, timestamp in sorted(row.odds_snapshot_times.items())
                },
                "odds_snapshot_ids": dict(sorted(row.odds_snapshot_ids.items())),
                "metrics": {"model": model_row, "market_baseline": market_row},
            }
        )

    model_ids = [row["match_id"] for row in predictions]
    market_ids = [row["match_id"] for row in predictions]
    if model_ids != market_ids:
        raise ValueError("model and market baseline samples are not paired")
    excluded_counts: dict[str, int] = {}
    for excluded_row in excluded:
        reason = str(excluded_row["reason"])
        excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
    return {
        "status": "evaluated" if predictions else "not_evaluable",
        "not_evaluable_reason": (
            None
            if predictions
            else fit_failure or "test_window_has_no_paired_model_market_observations"
        ),
        "window_index": split.index,
        "final_holdout": split.final_holdout,
        "window_role": (
            "predeclared_final_holdout"
            if split.final_holdout
            else "rolling_latest_diagnostic"
            if split.index is None
            else "exploratory_fold"
        ),
        "test_start": split.test_start.isoformat(),
        "test_end": split.test_end.isoformat(),
        "train_cutoff": manifest["cutoff_at"],
        "source_code_fingerprint_sha256": code_fingerprint["sha256"],
        "training_match_count": len(dataset.samples),
        "training_sample_ids_sha256": content_sha256(fit_match_ids),
        "training_manifest_sha256": manifest["sha256"],
        "training_excluded_by_reason": training_excluded_counts,
        "training_excluded": training_excluded,
        "artifact_identity_sha256": (
            artifact_identity["identity_sha256"] if artifact_identity is not None else None
        ),
        "artifact_parameters_sha256": (
            artifact_identity["sha256"] if artifact_identity is not None else None
        ),
        "fit_input_manifest_sha256": manifest["sha256"],
        "candidate_count": len(scoped_matches),
        "sample_count": len(predictions),
        "model_match_ids": model_ids,
        "market_match_ids": market_ids,
        "model_market_match_ids": model_ids,
        "excluded_by_reason": excluded_counts,
        "excluded": excluded,
        "metrics": {
            "model": _research_metric_summary(model_metrics),
            "market_baseline": _research_metric_summary(market_metrics),
            "paired_model_market": _research_paired_metric_comparison(
                predictions, predeclared_window=split.final_holdout
            ),
        },
        "predictions": predictions,
    }


def evaluate_research_reconstruction(
    matches: Sequence[ResearchMatch],
    config: ResearchEvaluationConfig | None = None,
) -> dict[str, Any]:
    """Refit Maher-SPF per chronological fold and once on a sealed final block."""
    config = config or ResearchEvaluationConfig()
    _validate_research_config(config)
    if len(matches) > config.max_matches:
        raise ValueError("materialized match count exceeds configured max_matches")
    match_ids = [row.candidate.match_id for row in matches]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("research matches must contain unique match IDs")
    if any(
        _research_datetime(row.candidate.kickoff_at).date() != row.business_date for row in matches
    ):
        raise ValueError("business_date must match the Beijing-local kickoff date")
    requested_season_id = config.competition_season_id
    if requested_season_id is not None:
        normalized_matches = [
            row for row in matches if row.competition_season_id == requested_season_id
        ]
        season_scope_excluded_count = len(matches) - len(normalized_matches)
        season_scope_status = "verified_requested_season"
    else:
        verified_season_ids = {
            row.competition_season_id
            for row in matches
            if type(row.competition_season_id) is int and row.competition_season_id > 0
        }
        if len(verified_season_ids) > 1:
            reason = "multiple_verified_seasons_require_separate_evaluations"
            return {
                "schema_version": "fqp.model-time-split-evaluation/v3",
                "evaluation_mode": "research_reconstruction",
                "status": "not_evaluable",
                "not_evaluable_reason": reason,
                "competition_season_id": None,
                "season_scope_status": "multiple_verified_seasons",
                "season_scope_excluded_match_count": 0,
                "source_snapshot_sha256": _research_source_snapshot(matches),
                "folds": [],
                "final_holdout": {
                    "status": "not_evaluable",
                    "not_evaluable_reason": reason,
                    "evaluation_count": 0,
                    "candidate_count": len(matches),
                    "sample_count": 0,
                    "excluded": [],
                    "metrics": {},
                },
                "excluded_by_reason": {reason: len(matches)},
                "official_prediction_writes": 0,
                "claims_model_beats_market": False,
            }
        normalized_matches = list(matches)
        season_scope_excluded_count = 0
        season_scope_status = (
            "single_verified_season"
            if matches
            and all(
                type(row.competition_season_id) is int and row.competition_season_id > 0
                for row in matches
            )
            else "season_identity_incomplete"
        )
    if season_scope_status == "season_identity_incomplete":
        reason = "verified_season_identity_required"
        missing_match_count = sum(
            type(row.competition_season_id) is not int or row.competition_season_id <= 0
            for row in matches
        )
        return {
            "schema_version": "fqp.model-time-split-evaluation/v3",
            "evaluation_mode": "research_reconstruction",
            "status": "not_evaluable",
            "not_evaluable_reason": reason,
            "competition_season_id": None,
            "season_scope_status": season_scope_status,
            "season_scope_excluded_match_count": missing_match_count,
            "source_snapshot_sha256": _research_source_snapshot(matches),
            "folds": [],
            "final_holdout": {
                "status": "not_evaluable",
                "not_evaluable_reason": reason,
                "evaluation_count": 0,
                "candidate_count": len(matches),
                "sample_count": 0,
                "excluded": [],
                "metrics": {},
            },
            "excluded_by_reason": {reason: missing_match_count},
            "official_prediction_writes": 0,
            "claims_model_beats_market": False,
        }
    if not normalized_matches:
        reason = "no_matches_with_requested_verified_competition_season"
        return {
            "schema_version": "fqp.model-time-split-evaluation/v3",
            "evaluation_mode": "research_reconstruction",
            "status": "not_evaluable",
            "not_evaluable_reason": reason,
            "competition_season_id": requested_season_id,
            "season_scope_status": season_scope_status,
            "season_scope_excluded_match_count": season_scope_excluded_count,
            "source_snapshot_sha256": _research_source_snapshot([]),
            "folds": [],
            "final_holdout": {
                "status": "not_evaluable",
                "not_evaluable_reason": reason,
                "evaluation_count": 0,
                "candidate_count": 0,
                "sample_count": 0,
                "excluded": [],
                "metrics": {},
            },
            "excluded_by_reason": {reason: season_scope_excluded_count},
            "official_prediction_writes": 0,
            "claims_model_beats_market": False,
        }
    normalized_matches = sorted(
        normalized_matches, key=lambda row: (row.business_date, row.candidate.match_id)
    )
    splits = build_research_time_splits(normalized_matches, config)
    code_fingerprint = _research_code_fingerprint()
    snapshot_sha256 = _research_source_snapshot(normalized_matches)

    fold_reports = [
        _evaluate_research_window(normalized_matches, split, config, code_fingerprint)
        for split in splits[:-1]
    ]
    final_report = _evaluate_research_window(
        normalized_matches, splits[-1], config, code_fingerprint
    )
    final_report["evaluation_count"] = int(final_report["status"] == "evaluated")
    all_windows = [*fold_reports, final_report]
    report_status = (
        "evaluated"
        if all(window["status"] == "evaluated" for window in all_windows)
        else "not_evaluable"
    )
    report_reason = next(
        (
            window["not_evaluable_reason"]
            for window in all_windows
            if window["status"] != "evaluated"
        ),
        None,
    )
    exclusion_counts: dict[str, int] = {}
    for window in [*fold_reports, final_report]:
        for reason, count in window["excluded_by_reason"].items():
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + count

    report = {
        "schema_version": "fqp.model-time-split-evaluation/v3",
        "evaluation_mode": "research_reconstruction",
        "status": report_status,
        "not_evaluable_reason": report_reason,
        "play_type": "spf",
        "model_name": "maher_poisson",
        "competition_season_id": requested_season_id
        or (
            normalized_matches[0].competition_season_id
            if season_scope_status == "single_verified_season"
            else None
        ),
        "season_scope_status": season_scope_status,
        "season_scope_excluded_match_count": season_scope_excluded_count,
        "baseline": {
            "name": "proportional_de-vig_market",
            "source": "complete official SPF odds vector available by each match prediction_as_of",
            "normalizer": "scripts.odds_conversion.normalize_probabilities",
        },
        "source_snapshot_sha256": snapshot_sha256,
        "team_identity_audit": [
            {
                "match_id": row.candidate.match_id,
                "business_date": row.business_date.isoformat(),
                "home": dict(row.team_identity["home"]),
                "away": dict(row.team_identity["away"]),
            }
            for row in normalized_matches
            if row.team_identity
            and any(
                row.team_identity.get(side, {}).get("name_match_count") != 1
                for side in ("home", "away")
            )
        ],
        "source_code_fingerprint": dict(code_fingerprint),
        "config": {
            "fold_count": config.fold_count,
            "test_window_days": config.test_window_days,
            "holdout_days": config.holdout_days,
            "predeclared_final_window_start": (
                config.predeclared_final_window_start.isoformat()
                if config.predeclared_final_window_start is not None
                else None
            ),
            "predeclared_final_window_end": (
                config.predeclared_final_window_end.isoformat()
                if config.predeclared_final_window_end is not None
                else None
            ),
            "min_team_matches": config.min_team_matches,
            "prediction_lead_minutes": config.prediction_lead_minutes,
            "competition_season_id": config.competition_season_id,
            "max_matches": config.max_matches,
        },
        "folds": fold_reports,
        "final_holdout": final_report,
        "excluded_by_reason": exclusion_counts,
        "official_prediction_writes": 0,
        "claims_model_beats_market": False,
    }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if len(encoded) > config.max_report_bytes:
        raise ValueError("research evaluation report exceeds configured size limit")
    return report


def _execute_read_only_snapshot(conn: Any, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    """Execute one bounded query in a fresh, closed repeatable-read snapshot."""
    try:
        from psycopg2.extensions import TRANSACTION_STATUS_IDLE
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required for PostgreSQL research reads") from exc
    if not callable(getattr(conn, "get_transaction_status", None)):
        raise TypeError("research materialization requires a psycopg2 connection")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("research materialization requires an idle connection")
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SET LOCAL lock_timeout = '2s'")
        cursor.execute("SET LOCAL statement_timeout = '15s'")
        cursor.execute(sql, tuple(params))
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    finally:
        try:
            conn.rollback()
        finally:
            cursor.close()


def _load_verified_competition_season_ids(conn: Any, match_ids: Sequence[int]) -> dict[int, int]:
    """Map official matches only through immutable verified JC season links."""
    unique_match_ids = sorted(
        {match_id for match_id in match_ids if type(match_id) is int and match_id > 0}
    )
    if not unique_match_ids:
        return {}
    availability = _execute_read_only_snapshot(
        conn,
        """SELECT to_regclass('football_fixture_source_links') IS NOT NULL AS has_links,
                  to_regclass('football_fixture_season_catalog') IS NOT NULL AS has_catalog,
                  EXISTS (
                      SELECT 1 FROM information_schema.columns
                      WHERE table_schema=current_schema()
                        AND table_name='official_matches'
                        AND column_name='source_match_id'
                  ) AS has_official_source_id""",
        (),
    )
    if not availability or not all(availability[0].values()):
        return {}
    rows = _execute_read_only_snapshot(
        conn,
        """SELECT official.id AS match_id,
                  COUNT(DISTINCT season.competition_season_id)::integer AS season_count,
                  MIN(season.competition_season_id)::bigint AS competition_season_id
           FROM official_matches official
           JOIN football_fixture_source_links link
             ON link.source_name='sporttery'
            AND link.id_system='jc.matchId'
            AND link.source_match_id=official.source_match_id
           JOIN football_fixture_season_catalog season
             ON season.fixture_id=link.fixture_id
            AND season.season_source_name='sporttery'
            AND season.season_id_system='uniform.leagueId+seasonId'
           WHERE official.id=ANY(%s)
           GROUP BY official.id""",
        (unique_match_ids,),
    )
    return {
        int(row["match_id"]): int(row["competition_season_id"])
        for row in rows
        if row["season_count"] == 1 and row["competition_season_id"] is not None
    }


def load_research_matches(
    conn: Any,
    *,
    max_matches: int = 5000,
    prediction_lead_minutes: int = 60,
) -> list[ResearchMatch]:
    """Read a bounded official-result/odds snapshot, then close its transaction."""
    if not 1 <= max_matches <= 5000:
        raise ValueError("max_matches must be between 1 and 5000")
    if not 1 <= prediction_lead_minutes <= 10080:
        raise ValueError("prediction_lead_minutes must be between 1 and 10080")
    sql = f"""
        WITH {RESULT_REVISION_VISIBILITY_CTE},
        selected_matches AS (
            SELECT m.id AS match_id,
                   m.business_date,
                   m.kickoff_time,
                   m.match_status,
                   m.home_team_name,
                   m.away_team_name,
                   r.id AS result_id,
                   r.official_publish_time,
                   r.full_home_goals AS home_goals,
                   r.full_away_goals AS away_goals,
                   r.result_status,
                   home_team.id AS home_team_id,
                   home_team.name_match_count AS home_team_name_match_count,
                   home_team.candidate_team_ids AS home_team_candidate_team_ids,
                   away_team.id AS away_team_id,
                   away_team.name_match_count AS away_team_name_match_count,
                   away_team.candidate_team_ids AS away_team_candidate_team_ids,
                   result_observations.label_observations
            FROM official_matches m
            LEFT JOIN official_results r ON r.match_id=m.id
            LEFT JOIN LATERAL (
                SELECT CASE WHEN COUNT(*) = 1 THEN MIN(t.id) END AS id,
                       COUNT(*)::integer AS name_match_count,
                       COALESCE(
                           array_agg(t.id ORDER BY t.id) FILTER (WHERE t.id IS NOT NULL),
                           ARRAY[]::BIGINT[]
                       ) AS candidate_team_ids
                FROM teams t
                WHERE t.team_name_cn=m.home_team_name
            ) home_team ON true
            LEFT JOIN LATERAL (
                SELECT CASE WHEN COUNT(*) = 1 THEN MIN(t.id) END AS id,
                       COUNT(*)::integer AS name_match_count,
                       COALESCE(
                           array_agg(t.id ORDER BY t.id) FILTER (WHERE t.id IS NOT NULL),
                           ARRAY[]::BIGINT[]
                       ) AS candidate_team_ids
                FROM teams t
                WHERE t.team_name_cn=m.away_team_name
            ) away_team ON true
            LEFT JOIN LATERAL (
                SELECT COALESCE(
                    jsonb_agg(jsonb_build_object(
                        'revision_id', revisions.id,
                        'result_id', CASE
                            WHEN revisions.evidence_json->>'official_result_id' ~ '^[1-9][0-9]*$'
                            THEN (revisions.evidence_json->>'official_result_id')::bigint
                            ELSE NULL END,
                        'fact_status', revisions.fact_status,
                        'home_goals', CASE
                            WHEN revisions.value_json->>'home_goals' ~ '^(0|[1-9][0-9]*)$'
                            THEN (revisions.value_json->>'home_goals')::integer
                            ELSE NULL END,
                        'away_goals', CASE
                            WHEN revisions.value_json->>'away_goals' ~ '^(0|[1-9][0-9]*)$'
                            THEN (revisions.value_json->>'away_goals')::integer
                            ELSE NULL END,
                        'published_at', revisions.published_at,
                        'first_acquired_at', revisions.first_acquired_at,
                        'available_at', revisions.available_at
                    ) ORDER BY revisions.available_at, revisions.revision),
                    '[]'::jsonb
                ) AS label_observations
                FROM (
                    SELECT revision.id, revision.revision, revision.fact_status,
                           revision.value_json, revision.evidence_json,
                           revision.published_at, revision.first_acquired_at,
                           visibility.committed_available_at AS available_at
                    FROM observation_streams stream
                    JOIN observation_revisions revision ON revision.stream_id=stream.id
                    JOIN result_revision_visibility visibility ON visibility.revision_id=revision.id
                    WHERE stream.match_id=m.id
                      AND stream.source_id='sporttery'
                      AND stream.domain='results'
                      AND stream.subject_key='full_time_score'
                      AND revision.evidence_kind='source_observation'
                    ORDER BY visibility.committed_available_at, revision.revision
                    LIMIT 65
                ) revisions
            ) result_observations ON true
            WHERE m.business_date IS NOT NULL
              AND m.kickoff_time IS NOT NULL
            ORDER BY m.business_date DESC, m.id DESC
            LIMIT %s
        )
        SELECT selected_matches.*,
               odds.id AS odds_snapshot_id,
               odds.option_code,
               odds.sp_value,
               odds.snapshot_time
        FROM selected_matches
        LEFT JOIN LATERAL (
            SELECT DISTINCT ON (CASE o.option_code
                                   WHEN 'h' THEN '3' WHEN 'd' THEN '1' WHEN 'a' THEN '0'
                                   ELSE o.option_code END)
                   o.id,
                   CASE o.option_code
                       WHEN 'h' THEN '3' WHEN 'd' THEN '1' WHEN 'a' THEN '0'
                       ELSE o.option_code
                   END AS option_code,
                   o.sp_value, o.snapshot_time
            FROM official_odds_snapshots o
            WHERE o.match_id=selected_matches.match_id
              AND o.play_type='spf'
              AND o.is_open=true
              AND o.sp_value > 1
              AND o.option_code IN ('h','d','a','3','1','0')
              AND o.snapshot_time <= selected_matches.kickoff_time
                    - (%s * INTERVAL '1 minute')
            ORDER BY CASE o.option_code
                         WHEN 'h' THEN '3' WHEN 'd' THEN '1' WHEN 'a' THEN '0'
                         ELSE o.option_code END,
                     o.snapshot_time DESC, o.id DESC
        ) odds ON true
        ORDER BY selected_matches.business_date,
                 selected_matches.match_id,
                 odds.option_code
    """
    rows = _execute_read_only_snapshot(conn, sql, (max_matches + 1, prediction_lead_minutes))
    competition_season_ids = _load_verified_competition_season_ids(
        conn, [int(row["match_id"]) for row in rows]
    )
    matches: dict[int, ResearchMatch] = {}
    for row in rows:
        match_id = int(row["match_id"])
        if match_id not in matches:
            kickoff = _research_datetime(row["kickoff_time"])
            candidate = CandidateMatch(
                match_id=match_id,
                result_id=(int(row["result_id"]) if row["result_id"] is not None else None),
                kickoff_at=kickoff,
                home_team_id=(
                    int(row["home_team_id"]) if row["home_team_id"] is not None else None
                ),
                away_team_id=(
                    int(row["away_team_id"]) if row["away_team_id"] is not None else None
                ),
                home_goals=(int(row["home_goals"]) if row["home_goals"] is not None else None),
                away_goals=(int(row["away_goals"]) if row["away_goals"] is not None else None),
                match_status=row["match_status"],
                official_publish_time=row["official_publish_time"],
                label_observations=tuple(
                    _normalize_result_observation(observation)
                    for observation in (row["label_observations"] or ())
                ),
            )
            matches[match_id] = ResearchMatch(
                candidate=candidate,
                business_date=row["business_date"],
                prediction_as_of=kickoff - timedelta(minutes=prediction_lead_minutes),
                odds_by_option={},
                odds_snapshot_times={},
                odds_snapshot_ids={},
                result_status=str(row["result_status"] or "").lower(),
                team_identity={
                    "home": {
                        "team_name": row["home_team_name"],
                        "selected_team_id": (
                            int(row["home_team_id"]) if row["home_team_id"] is not None else None
                        ),
                        "name_match_count": int(row["home_team_name_match_count"]),
                        "candidate_team_ids": [
                            int(team_id) for team_id in row["home_team_candidate_team_ids"]
                        ],
                    },
                    "away": {
                        "team_name": row["away_team_name"],
                        "selected_team_id": (
                            int(row["away_team_id"]) if row["away_team_id"] is not None else None
                        ),
                        "name_match_count": int(row["away_team_name_match_count"]),
                        "candidate_team_ids": [
                            int(team_id) for team_id in row["away_team_candidate_team_ids"]
                        ],
                    },
                },
                competition_season_id=competition_season_ids.get(match_id),
            )
        current = matches[match_id]
        if row["option_code"] is not None:
            odds = dict(current.odds_by_option)
            times = dict(current.odds_snapshot_times)
            ids = dict(current.odds_snapshot_ids)
            option = str(row["option_code"])
            odds[option] = float(row["sp_value"])
            times[option] = row["snapshot_time"]
            ids[option] = int(row["odds_snapshot_id"])
            matches[match_id] = ResearchMatch(
                candidate=current.candidate,
                business_date=current.business_date,
                prediction_as_of=current.prediction_as_of,
                odds_by_option=odds,
                odds_snapshot_times=times,
                odds_snapshot_ids=ids,
                result_status=current.result_status,
                team_identity=current.team_identity,
                competition_season_id=current.competition_season_id,
            )
    if len(matches) > max_matches:
        raise ValueError("materialized match count exceeds max_matches")
    return sorted(matches.values(), key=lambda row: (row.business_date, row.candidate.match_id))


def evaluate_prediction_replay(conn: Any, prediction_run_id: str) -> dict[str, Any]:
    """Evaluate only complete, stored SPF groups from one P106-03 prediction run."""
    from scripts.evaluation_metrics import compute_match_metrics
    from scripts.model_prediction_run_identity import (
        verify_prediction_artifact_binding,
        verify_prediction_group_output_manifest,
        verify_prediction_run_manifest,
        verify_prediction_run_output_manifest,
    )

    if not isinstance(prediction_run_id, str) or not prediction_run_id.strip():
        raise ValueError("prediction_run_id is required")
    sql = """
        SELECT g.id AS group_id, g.match_id, g.play_type, g.predict_time,
               g.expected_options, g.probability_vector, g.output_sha256,
               g.output_manifest AS group_output_manifest,
               g.output_manifest_canonical AS group_output_manifest_canonical,
               g.odds_snapshot_ids, g.odds_snapshot_times,
               g.artifact_identity, g.input_fence, g.model_version_id,
               g.provenance_status AS group_provenance_status,
               g.group_status, r.run_status, r.provenance_status AS run_provenance_status,
               r.run_manifest_sha256, r.model_manifest_sha256, r.input_manifest_sha256,
               r.run_manifest, r.model_manifest, r.input_manifest,
               r.output_summary, r.output_manifest_sha256,
               r.output_manifest AS run_output_manifest,
               r.output_manifest_canonical AS run_output_manifest_canonical,
               g.market_variant, mv.model_name, mv.is_active AS model_is_active,
               transaction_timestamp() AS replay_observed_at,
               m.kickoff_time,
               result.result_status, result.spf_result,
               result.result_id,
               outputs.market_vector, outputs.output_snapshot_ids, outputs.option_count
        FROM model_prediction_groups g
        JOIN model_prediction_runs r ON r.id=g.run_id
        JOIN official_matches m ON m.id=g.match_id
        LEFT JOIN LATERAL (
            SELECT id AS result_id, result_status, spf_result
            FROM official_results
            WHERE match_id=g.match_id
            ORDER BY official_publish_time DESC NULLS LAST, id DESC
            LIMIT 1
        ) result ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_object_agg(option_map.option_code, mp.market_probability) AS market_vector,
                   jsonb_object_agg(option_map.option_code, mp.odds_snapshot_id) AS output_snapshot_ids,
                   COUNT(DISTINCT option_map.option_code) AS option_count
            FROM model_prediction_group_options option_map
            JOIN model_predictions mp ON mp.id=option_map.prediction_id
            WHERE option_map.group_id=g.id
        ) outputs ON true
        JOIN model_versions mv ON mv.id=g.model_version_id
        WHERE g.run_id=%s
        ORDER BY g.match_id, g.model_version_id, g.play_type, g.market_variant, g.id
    """
    rows = _execute_read_only_snapshot(conn, sql, (prediction_run_id,))
    if not rows:
        raise ValueError("prediction run has no stored output groups")
    competition_season_ids = _load_verified_competition_season_ids(
        conn, [int(row["match_id"]) for row in rows]
    )

    evaluated = []
    excluded: list[dict[str, Any]] = []
    run_manifest_sha256 = None
    run_integrity_error = None
    try:
        first = rows[0]
        verify_prediction_run_manifest(
            run_manifest=first["run_manifest"],
            run_manifest_sha256=first["run_manifest_sha256"],
            model_manifest=first["model_manifest"],
            model_manifest_sha256=first["model_manifest_sha256"],
            input_manifest=first["input_manifest"],
            input_manifest_sha256=first["input_manifest_sha256"],
        )
        output_summary = first["output_summary"]
        if not isinstance(output_summary, Mapping):
            raise ValueError("prediction output summary is missing")
        completed_hashes = [
            row["output_sha256"] for row in rows if row["group_status"] == "complete"
        ]
        verify_prediction_run_output_manifest(
            output_manifest=first["run_output_manifest"],
            output_manifest_sha256=first["output_manifest_sha256"],
            output_manifest_canonical=first["run_output_manifest_canonical"],
            output_summary=output_summary,
            expected_group_hashes=completed_hashes,
        )
        if int(output_summary.get("completed_groups", -1)) != len(completed_hashes) or int(
            output_summary.get("skipped_groups", -1)
        ) != len(output_summary.get("missing_groups", [])):
            raise ValueError("prediction run output summary is inconsistent")
    except (TypeError, ValueError) as exc:
        run_integrity_error = str(exc)

    for row in rows:
        run_manifest_sha256 = row["run_manifest_sha256"]
        reason = "prediction_run_integrity_invalid" if run_integrity_error else None
        if row["group_status"] != "complete":
            reason = reason or "prediction_group_incomplete"
        elif row["run_status"] not in {"completed", "partial"}:
            reason = "prediction_run_not_published"
        elif (
            row["group_provenance_status"] != "complete"
            or row["run_provenance_status"] != "complete"
        ):
            reason = "prediction_provenance_incomplete"
        elif not isinstance(row["artifact_identity"], Mapping):
            reason = "artifact_identity_missing"
        elif row["artifact_identity"].get("provenance_status") != "complete":
            reason = "artifact_identity_incomplete"
        if reason is None:
            try:
                verify_prediction_group_output_manifest(
                    output_manifest=row["group_output_manifest"],
                    output_sha256=row["output_sha256"],
                    output_manifest_canonical=row["group_output_manifest_canonical"],
                    match_id=int(row["match_id"]),
                    model_version_id=int(row["model_version_id"]),
                    play_type=str(row["play_type"]),
                    market_variant=str(row["market_variant"] or ""),
                    predict_time=row["predict_time"],
                    expected_options=row["expected_options"],
                    probability_vector=row["probability_vector"],
                )
                verify_prediction_artifact_binding(
                    row["model_manifest"],
                    row["artifact_identity"],
                    model_version_id=int(row["model_version_id"]),
                )
            except (TypeError, ValueError) as _exc:
                reason = "prediction_group_integrity_invalid"
        if reason is None:
            if row["play_type"] != "spf":
                reason = "unsupported_play_type"
            elif row["predict_time"] >= row["kickoff_time"]:
                reason = "prediction_not_before_kickoff"
            elif row["result_status"] not in {"final", "confirmed"} or row["spf_result"] not in {
                "3",
                "1",
                "0",
            }:
                reason = "official_result_not_final"
        expected = sorted(str(option) for option in (row["expected_options"] or []))
        model = row["probability_vector"] or {}
        market = row["market_vector"] or {}
        if reason is None and (expected != ["0", "1", "3"] or row["option_count"] != 3):
            reason = "incomplete_prediction_group"
        if reason is None and (set(model) != {"3", "1", "0"} or set(market) != {"3", "1", "0"}):
            reason = "incomplete_probability_vector"
        if reason is None:
            recorded_ids = row["odds_snapshot_ids"] or {}
            output_ids = row["output_snapshot_ids"] or {}
            recorded_times = row["odds_snapshot_times"] or {}
            if (
                set(recorded_ids) != {"3", "1", "0"}
                or set(output_ids) != {"3", "1", "0"}
                or set(recorded_times) != {"3", "1", "0"}
                or any(str(recorded_ids[key]) != str(output_ids[key]) for key in recorded_ids)
            ):
                reason = "market_snapshot_identity_missing"
            elif any(
                _research_datetime(recorded_times[key]) > row["predict_time"]
                for key in ("3", "1", "0")
            ):
                reason = "market_snapshot_after_prediction_time"
        if reason is not None:
            excluded.append({"match_id": int(row["match_id"]), "reason": reason})
            continue
        try:
            model_probs = {option: float(model[option]) for option in ("3", "1", "0")}
            market_probs = {option: float(market[option]) for option in ("3", "1", "0")}
        except (TypeError, ValueError) as _exc:
            excluded.append(
                {
                    "match_id": int(row["match_id"]),
                    "reason": "invalid_probability_vector",
                }
            )
            continue
        if any(
            not math.isfinite(value) or value < 0
            for value in (*model_probs.values(), *market_probs.values())
        ):
            excluded.append(
                {
                    "match_id": int(row["match_id"]),
                    "reason": "invalid_probability_vector",
                }
            )
            continue
        if not math.isclose(math.fsum(model_probs.values()), 1.0, abs_tol=1e-5) or not math.isclose(
            math.fsum(market_probs.values()), 1.0, abs_tol=1e-5
        ):
            excluded.append(
                {
                    "match_id": int(row["match_id"]),
                    "reason": "unnormalized_probability_vector",
                }
            )
            continue
        model_metric = compute_match_metrics(
            model_probs, market_probs, row["spf_result"], "stored_prediction"
        )
        market_metric = compute_match_metrics(
            market_probs, market_probs, row["spf_result"], "market_baseline"
        )
        evaluated.append(
            {
                "group_id": str(row["group_id"]),
                "match_id": int(row["match_id"]),
                "model_version_id": int(row["model_version_id"]),
                "play_type": "spf",
                "business_date": row["kickoff_time"].date().isoformat(),
                "competition_season_id": competition_season_ids.get(int(row["match_id"])),
                "predict_time": row["predict_time"].isoformat(),
                "result_id": int(row["result_id"]),
                "model_name": row["model_name"],
                "model_is_active": row["model_is_active"] is True,
                "output_sha256": row["output_sha256"],
                "artifact_identity": row["artifact_identity"],
                "input_fence": row["input_fence"],
                "odds_snapshot_ids": row["odds_snapshot_ids"],
                "odds_snapshot_times": row["odds_snapshot_times"],
                "model_probabilities": model_probs,
                "market_probabilities": market_probs,
                "actual_result": row["spf_result"],
                "metrics": {
                    "model": {
                        name: model_metric[name] for name in ("brier_score", "log_loss", "rps")
                    },
                    "market_baseline": {
                        name: market_metric[name] for name in ("brier_score", "log_loss", "rps")
                    },
                },
            }
        )
    if not evaluated:
        raise ValueError("prediction run has no complete paired SPF observations")
    model_ids = [row["match_id"] for row in evaluated]
    market_ids = [row["match_id"] for row in evaluated]
    return {
        "schema_version": "fqp.model-time-split-evaluation/v1",
        "evaluation_mode": "prediction_replay",
        "prediction_run_id": prediction_run_id,
        "prediction_run_manifest_sha256": run_manifest_sha256,
        "model_manifest_sha256": rows[0]["model_manifest_sha256"],
        "input_manifest_sha256": rows[0]["input_manifest_sha256"],
        "replay_observed_at": rows[0]["replay_observed_at"].isoformat(),
        "play_type": "spf",
        "sample_count": len(evaluated),
        "model_match_ids": model_ids,
        "market_match_ids": market_ids,
        "model_market_match_ids": model_ids,
        "metrics": {
            "model": _research_metric_summary([row["metrics"]["model"] for row in evaluated]),
            "market_baseline": _research_metric_summary(
                [row["metrics"]["market_baseline"] for row in evaluated]
            ),
        },
        "excluded": excluded,
        "predictions": evaluated,
        "official_prediction_writes": 0,
    }


def compare_prediction_replay_reports(
    challenger_report: Mapping[str, Any],
    incumbent_report: Mapping[str, Any],
    *,
    challenger_model_version_id: int | None = None,
    incumbent_model_version_id: int | None = None,
    require_active_incumbent: bool = False,
    predeclared_window: bool = False,
) -> dict[str, Any]:
    """Compare replayed models only on the same fixture, time, result and market.

    Reports are materialized independently, so every shared observation is
    re-paired by immutable result ID and odds snapshot identity. This report is
    descriptive only; it cannot authorize promotion.
    """

    def selected_rows(
        report: Mapping[str, Any], side: str, requested_model_id: int | None
    ) -> tuple[str, int, list[dict[str, Any]]]:
        if (
            not isinstance(report, Mapping)
            or report.get("schema_version") != "fqp.model-time-split-evaluation/v1"
            or report.get("evaluation_mode") != "prediction_replay"
        ):
            raise ValueError(f"{side} report must be a prediction_replay report")
        run_id = report.get("prediction_run_id")
        rows = report.get("predictions")
        if not isinstance(run_id, str) or not run_id.strip() or not isinstance(rows, list):
            raise ValueError(f"{side} replay report identity is incomplete")
        for field_name in (
            "prediction_run_manifest_sha256",
            "model_manifest_sha256",
            "input_manifest_sha256",
        ):
            digest = report.get(field_name)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(f"{side} replay report has an invalid {field_name}")
        observed_at = report.get("replay_observed_at")
        try:
            parsed_observed_at = (
                datetime.fromisoformat(observed_at) if isinstance(observed_at, str) else None
            )
        except ValueError:
            parsed_observed_at = None
        if (
            parsed_observed_at is None
            or parsed_observed_at.tzinfo is None
            or parsed_observed_at.utcoffset() is None
        ):
            raise ValueError(f"{side} replay report has an invalid replay_observed_at")
        if report.get("official_prediction_writes") != 0:
            raise ValueError(f"{side} replay report must be read-only")
        version_ids = {
            row.get("model_version_id")
            for row in rows
            if isinstance(row, Mapping) and type(row.get("model_version_id")) is int
        }
        if requested_model_id is None:
            if len(version_ids) != 1:
                raise ValueError(f"{side}_model_version_id must be explicit for a multi-model run")
            model_id = next(iter(version_ids))
        else:
            if type(requested_model_id) is not int or requested_model_id <= 0:
                raise ValueError(f"{side}_model_version_id must be a positive integer")
            model_id = requested_model_id
        if type(model_id) is not int or model_id <= 0:
            raise ValueError(f"{side}_model_version_id must be a positive integer")
        selected = [
            dict(row)
            for row in rows
            if isinstance(row, Mapping) and row.get("model_version_id") == model_id
        ]
        if not selected:
            raise ValueError(f"{side}_model_version_id is absent from its replay report")
        if (
            side == "incumbent"
            and require_active_incumbent
            and any(row.get("model_is_active") is not True for row in selected)
        ):
            raise ValueError("incumbent replay report does not attest an active model version")
        by_match: dict[int, dict[str, Any]] = {}
        for row in selected:
            match_id = row.get("match_id")
            if type(match_id) is not int or match_id <= 0:
                raise ValueError(f"{side} replay contains an invalid match ID")
            if match_id in by_match:
                raise ValueError(f"{side} replay contains duplicate match IDs")
            output_digest = row.get("output_sha256")
            if (
                not isinstance(output_digest, str)
                or len(output_digest) != 64
                or any(character not in "0123456789abcdef" for character in output_digest)
            ):
                raise ValueError(f"{side} replay contains an invalid output digest")
            by_match[match_id] = row
        return run_id, model_id, list(by_match.values())

    challenger_run_id, challenger_model_id, challenger_rows = selected_rows(
        challenger_report, "challenger", challenger_model_version_id
    )
    incumbent_run_id, incumbent_model_id, incumbent_rows = selected_rows(
        incumbent_report, "incumbent", incumbent_model_version_id
    )
    if challenger_run_id == incumbent_run_id:
        raise ValueError("challenger and incumbent must use different prediction runs")
    if challenger_model_id == incumbent_model_id:
        raise ValueError("challenger and incumbent must use different model versions")
    challenger_names = {row.get("model_name") for row in challenger_rows}
    incumbent_names = {
        row.get("model_name")
        for row in incumbent_rows
        if row.get("model_version_id") == incumbent_model_id
    }
    if len(challenger_names) != 1 or None in challenger_names:
        raise ValueError("challenger replay must identify exactly one model name")
    if len(incumbent_names) != 1 or None in incumbent_names:
        raise ValueError("incumbent replay must identify exactly one model name")

    challenger_by_match = {row["match_id"]: row for row in challenger_rows}
    incumbent_by_match = {row["match_id"]: row for row in incumbent_rows}
    paired: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    source_exclusions = [
        {"side": side, **dict(item)}
        for side, report in (
            ("challenger", challenger_report),
            ("incumbent", incumbent_report),
        )
        for item in report.get("excluded", [])
        if isinstance(item, Mapping)
    ]
    for match_id in sorted(challenger_by_match.keys() | incumbent_by_match.keys()):
        challenger = challenger_by_match.get(match_id)
        incumbent = incumbent_by_match.get(match_id)
        if challenger is None:
            excluded.append({"match_id": match_id, "reason": "challenger_prediction_missing"})
            continue
        if incumbent is None:
            excluded.append({"match_id": match_id, "reason": "incumbent_prediction_missing"})
            continue
        reason: str | None = None
        if challenger.get("play_type") != "spf" or incumbent.get("play_type") != "spf":
            reason = "unsupported_play_type"
        elif challenger.get("business_date") != incumbent.get("business_date"):
            reason = "business_date_mismatch"
        elif (
            type(challenger.get("competition_season_id")) is not int
            or challenger["competition_season_id"] <= 0
            or type(incumbent.get("competition_season_id")) is not int
            or incumbent["competition_season_id"] <= 0
        ):
            reason = "season_identity_missing"
        elif challenger.get("competition_season_id") != incumbent.get("competition_season_id"):
            reason = "competition_season_mismatch"
        elif not isinstance(challenger.get("predict_time"), datetime | str) or not isinstance(
            incumbent.get("predict_time"), datetime | str
        ):
            reason = "prediction_as_of_missing"
        elif _research_datetime(challenger["predict_time"]) != _research_datetime(
            incumbent["predict_time"]
        ):
            reason = "prediction_as_of_mismatch"
        elif (
            type(challenger.get("result_id")) is not int
            or challenger["result_id"] <= 0
            or type(incumbent.get("result_id")) is not int
            or incumbent["result_id"] <= 0
        ):
            reason = "result_identity_missing"
        elif challenger.get("result_id") != incumbent.get("result_id") or challenger.get(
            "actual_result"
        ) != incumbent.get("actual_result"):
            reason = "result_identity_mismatch"
        elif (
            challenger.get("odds_snapshot_ids") != incumbent.get("odds_snapshot_ids")
            or challenger.get("odds_snapshot_times") != incumbent.get("odds_snapshot_times")
            or challenger.get("market_probabilities") != incumbent.get("market_probabilities")
        ):
            reason = "market_snapshot_mismatch"
        if reason is not None:
            excluded.append({"match_id": match_id, "reason": reason})
            continue
        challenger_metrics = challenger.get("metrics")
        incumbent_metrics = incumbent.get("metrics")
        if (
            not isinstance(challenger_metrics, Mapping)
            or not isinstance(challenger_metrics.get("model"), Mapping)
            or not isinstance(challenger_metrics.get("market_baseline"), Mapping)
            or not isinstance(incumbent_metrics, Mapping)
            or not isinstance(incumbent_metrics.get("model"), Mapping)
            or not isinstance(incumbent_metrics.get("market_baseline"), Mapping)
        ):
            excluded.append({"match_id": match_id, "reason": "paired_metrics_missing"})
            continue
        paired.append(
            {
                "match_id": match_id,
                "business_date": challenger["business_date"],
                "competition_season_id": challenger["competition_season_id"],
                "prediction_as_of": challenger["predict_time"],
                "result_id": challenger["result_id"],
                "actual_result": challenger["actual_result"],
                "challenger_probabilities": challenger["model_probabilities"],
                "incumbent_probabilities": incumbent["model_probabilities"],
                "market_probabilities": challenger["market_probabilities"],
                "challenger_artifact_identity": challenger["artifact_identity"],
                "incumbent_artifact_identity": incumbent["artifact_identity"],
                "odds_snapshot_ids": challenger["odds_snapshot_ids"],
                "challenger_output_sha256": challenger["output_sha256"],
                "incumbent_output_sha256": incumbent["output_sha256"],
                "metrics": {
                    "challenger": dict(challenger_metrics["model"]),
                    "incumbent": dict(incumbent_metrics["model"]),
                    "market_baseline": dict(challenger_metrics["market_baseline"]),
                },
            }
        )

    challenger_metrics = [row["metrics"]["challenger"] for row in paired]
    incumbent_metrics = [row["metrics"]["incumbent"] for row in paired]
    market_metrics = [row["metrics"]["market_baseline"] for row in paired]
    return {
        "schema_version": "fqp.paired-prediction-run-evaluation/v1",
        "evaluation_mode": "paired_prediction_replay",
        "status": "evaluated_descriptive_only" if paired else "not_evaluable",
        "challenger_run_id": challenger_run_id,
        "challenger_run_manifest_sha256": challenger_report.get("prediction_run_manifest_sha256"),
        "challenger_model_manifest_sha256": challenger_report.get("model_manifest_sha256"),
        "challenger_input_manifest_sha256": challenger_report.get("input_manifest_sha256"),
        "challenger_replay_observed_at": challenger_report["replay_observed_at"],
        "challenger_model_version_id": challenger_model_id,
        "challenger_model_name": next(iter(challenger_names)),
        "incumbent_run_id": incumbent_run_id,
        "incumbent_run_manifest_sha256": incumbent_report.get("prediction_run_manifest_sha256"),
        "incumbent_model_manifest_sha256": incumbent_report.get("model_manifest_sha256"),
        "incumbent_input_manifest_sha256": incumbent_report.get("input_manifest_sha256"),
        "incumbent_replay_observed_at": incumbent_report["replay_observed_at"],
        "incumbent_model_version_id": incumbent_model_id,
        "incumbent_model_name": next(iter(incumbent_names)),
        "play_type": "spf",
        "sample_count": len(paired),
        "challenger_match_ids": sorted(challenger_by_match),
        "incumbent_match_ids": sorted(incumbent_by_match),
        "paired_match_ids": [row["match_id"] for row in paired],
        "excluded": excluded,
        "source_exclusions": source_exclusions,
        "decision_eligible": False,
        "promotion_eligible": False,
        "official_prediction_writes": 0,
        "metrics": {
            "challenger": _research_metric_summary(challenger_metrics),
            "incumbent": _research_metric_summary(incumbent_metrics),
            "market_baseline": _research_metric_summary(market_metrics),
            "paired_challenger_incumbent": _research_paired_metric_comparison(
                paired,
                left_name="challenger",
                right_name="incumbent",
                predeclared_window=predeclared_window,
            ),
        },
        "predictions": paired,
    }


def store_research_evaluation_run(
    conn: Any,
    report: Mapping[str, Any],
    *,
    name: str,
) -> int:
    """Atomically store a bounded, mode-tagged report in existing backtest JSONB."""
    if report.get("evaluation_mode") not in {
        "research_reconstruction",
        "prediction_replay",
        "paired_prediction_replay",
    }:
        raise ValueError("evaluation_mode must distinguish research from stored prediction replay")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ValueError("research evaluation name must contain 1 to 255 characters")
    payload = json.dumps(dict(report), ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(payload.encode("utf-8")) > 5_000_000:
        raise ValueError("research evaluation report exceeds 5 MB")
    try:
        from psycopg2.extensions import TRANSACTION_STATUS_IDLE
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required for research evaluation storage") from exc
    if not callable(getattr(conn, "get_transaction_status", None)):
        raise TypeError("research result storage requires a psycopg2 connection")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("research result storage requires an idle connection")
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO backtest_runs (name, description, config, status, started_at)
                   VALUES (%s, %s, %s::jsonb, 'running', NOW()) RETURNING id""",
                (
                    name.strip(),
                    "Offline P106-04 evaluation; not an official prediction run.",
                    payload,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("research backtest run ID was not returned")
            run_id = int(row[0])
            cursor.execute(
                """UPDATE backtest_runs SET status='completed', finished_at=NOW()
                   WHERE id=%s AND status='running'""",
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("research backtest run could not be completed")
        conn.commit()
        return run_id
    except Exception:
        conn.rollback()
        raise


# —— 自测 ——

if __name__ == "__main__":
    print("=== 回测引擎测试 ===\n")

    # 构造合成数据进行数学验证

    # 1. 测试指标计算
    print("1. 指标计算测试")
    fake_bets = [
        BetRecord(
            1,
            "2025-01-01",
            "maher_poisson",
            "3",
            0.45,
            0.42,
            2.20,
            1.0,
            "3",
            1.20,
            0.10,
            0.65,
        ),
        BetRecord(
            2,
            "2025-01-02",
            "maher_poisson",
            "1",
            0.30,
            0.28,
            3.50,
            1.0,
            "1",
            2.50,
            0.05,
            0.55,
        ),
        BetRecord(
            3,
            "2025-01-03",
            "maher_poisson",
            "0",
            0.35,
            0.33,
            2.80,
            1.0,
            "3",
            -1.00,
            0.08,
            0.60,
        ),
        BetRecord(
            4,
            "2025-01-04",
            "maher_poisson",
            "3",
            0.50,
            0.48,
            1.90,
            1.0,
            "3",
            0.90,
            0.12,
            0.70,
        ),
        BetRecord(
            5,
            "2025-01-05",
            "maher_poisson",
            "1",
            0.28,
            0.26,
            3.80,
            1.0,
            "0",
            -1.00,
            0.02,
            0.45,
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
