"""模型评估指标。

计算预测质量指标：
  1. Brier Score      — 均方误差 (多分类版本)
  2. Log Loss          — 交叉熵
  3. CLV               — Closing Line Value (模型概率 vs 市场最终概率)
  4. Calibration Error — 校准误差 (预测概率 vs 实际频率)
  5. RPS               — Ranked Probability Score (有序分类)

存储到 market_efficiency_metrics 表（已在 sql/03 中创建）。
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any

# Ensure project root on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# —— 核心指标 ——


def brier_score(
    probs: dict[str, float],
    actual: str,
) -> float:
    """多分类 Brier Score。

    BS = (1/N) Σ_i (p_i - o_i)²

    其中 p_i 是预测概率，o_i 是指示变量（正确=1，错误=0）。
    范围 [0, 1]，越低越好。完美 = 0。

    Args:
        probs: {"3": 0.45, "1": 0.25, "0": 0.30}
        actual: "3", "1", or "0"

    Returns:
        Brier score (单场比赛)
    """
    total = 0.0
    for opt, p in probs.items():
        o_i = 1.0 if opt == actual else 0.0
        total += (p - o_i) ** 2
    return total


def log_loss_score(
    probs: dict[str, float],
    actual: str,
    eps: float = 1e-15,
) -> float:
    """对数损失 (Log Loss / Cross-Entropy)。

    LL = -Σ o_i * log(p_i)

    范围 [0, +∞)，越低越好。完美 = 0。
    严重惩罚自信的错误预测。
    """
    total = 0.0
    for opt, p in probs.items():
        o_i = 1.0 if opt == actual else 0.0
        if o_i > 0:
            p_clamp = max(eps, min(1.0 - eps, p))
            total -= math.log(p_clamp)
    return total


def rps_score(
    probs: dict[str, float],
    actual: str,
    ordering: list[str] | None = None,
) -> float:
    """Ranked Probability Score (有序分类)。

    RPS = Σ_j (C_j_pred - C_j_actual)²

    其中 C_j 是累积概率。对于足球 1x2 (胜/平/负)，
    有序性较弱但仍可用于评估。

    Args:
        probs: 预测概率
        actual: 实际结果
        ordering: 选项排序 (e.g., ["3", "1", "0"] 按结果强度)

    Returns:
        RPS score
    """
    if ordering is None:
        ordering = ["3", "1", "0"]

    cum_pred = 0.0
    cum_actual = 0.0
    total = 0.0

    for opt in ordering:
        cum_pred += probs.get(opt, 0.0)
        cum_actual += 1.0 if opt == actual else 0.0
        total += (cum_pred - cum_actual) ** 2

    return total / (len(ordering) - 1) if len(ordering) > 1 else total


def clv(
    model_prob: float,
    market_prob_before: float,
    market_prob_after: float | None = None,
) -> float:
    """Closing Line Value (CLV)。

    衡量模型概率相对于市场最终赔率的优势。

    CLV = model_prob - market_prob_final

    > 0 表示模型比市场更看好该结果（正EV机会）。
    如果没有 market_prob_after，则比较 model_prob vs market_prob_before。

    Args:
        model_prob: 模型预测概率
        market_prob_before: 开盘隐含概率
        market_prob_after: 收盘隐含概率 (如果有)

    Returns:
        CLV score
    """
    ref = market_prob_after if market_prob_after is not None else market_prob_before
    return model_prob - ref


def probability_gap(
    model_prob: float,
    market_prob: float,
) -> float:
    """概率差距：模型概率 - 市场概率。"""
    return model_prob - market_prob


# —— 批量计算 ——


def compute_match_metrics(
    probs: dict[str, float],
    market_probs: dict[str, float],
    actual: str,
    model_name: str = "unknown",
) -> dict[str, Any]:
    """计算单场比赛的所有评估指标。

    Returns:
        Dict with brier, log_loss, rps, clv (per option), probability_gap (per option)
    """
    bs = brier_score(probs, actual)
    ll = log_loss_score(probs, actual)
    rps = rps_score(probs, actual)

    clv_scores = {}
    gaps = {}
    for opt in ["3", "1", "0"]:
        mp = probs.get(opt, 0.0)
        mrk = market_probs.get(opt, 0.0)
        clv_scores[f"clv_{opt}"] = round(clv(mp, mrk), 6)
        gaps[f"gap_{opt}"] = round(probability_gap(mp, mrk), 6)

    return {
        "model_name": model_name,
        "brier_score": round(bs, 6),
        "log_loss": round(ll, 6),
        "rps": round(rps, 6),
        **clv_scores,
        **gaps,
    }


def compute_calibration(
    predictions: list[tuple[float, int]],
    n_bins: int = 10,
) -> dict[str, Any]:
    """计算校准曲线和校准误差。

    Args:
        predictions: [(predicted_probability, actual_outcome), ...]
        n_bins: 分箱数

    Returns:
        {"bins": [(bin_center, pred_mean, actual_freq, count), ...],
         "ece": float,  # Expected Calibration Error
         "mce": float}  # Maximum Calibration Error
    """
    if len(predictions) < n_bins:
        return {"bins": [], "ece": 0.0, "mce": 0.0, "error": "insufficient data"}

    # 按预测概率排序并分箱
    sorted_preds = sorted(predictions, key=lambda x: x[0])
    bin_size = len(sorted_preds) // n_bins

    bins = []
    ece_total = 0.0
    mce = 0.0

    for b in range(n_bins):
        start = b * bin_size
        end = start + bin_size if b < n_bins - 1 else len(sorted_preds)
        chunk = sorted_preds[start:end]

        if not chunk:
            continue

        pred_mean = sum(p[0] for p in chunk) / len(chunk)
        actual_freq = sum(p[1] for p in chunk) / len(chunk)
        count = len(chunk)

        cal_error = abs(pred_mean - actual_freq)
        ece_total += cal_error * count
        mce = max(mce, cal_error)

        bins.append(
            {
                "bin_center": round(pred_mean, 4),
                "pred_mean": round(pred_mean, 4),
                "actual_freq": round(actual_freq, 4),
                "count": count,
            }
        )

    ece = ece_total / len(predictions)

    return {
        "bins": bins,
        "ece": round(ece, 6),
        "mce": round(mce, 6),
    }


# —— 存储层 ——


def store_evaluation_metrics(
    conn: Any,
    metrics_batch: list[dict[str, Any]],
) -> int:
    """将评估指标写入 market_efficiency_metrics 表。

    Args:
        conn: DB 连接
        metrics_batch: compute_match_metrics 输出列表

    Returns:
        写入记录数
    """
    stored = 0
    with conn.cursor() as cur:
        for m in metrics_batch:
            try:
                cur.execute(
                    """INSERT INTO market_efficiency_metrics
                       (match_id, model_version_id, snapshot_time,
                        play_type, option_code,
                        probability_gap, clv_score, favourite_longshot_score,
                        market_signal_level,
                        brier_score, log_loss, rps,
                        created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
                    (
                        m.get("match_id"),
                        m.get("model_version_id"),
                        m.get("predict_time"),
                        m.get("play_type", "spf"),
                        m.get("option_code", "3"),
                        m.get("probability_gap"),
                        m.get("clv_score"),
                        m.get("favourite_longshot_score"),
                        m.get("market_signal_level"),
                        m.get("brier_score"),
                        m.get("log_loss"),
                        m.get("rps"),
                    ),
                )
                stored += 1
            except Exception:
                pass
    conn.commit()
    return stored


# —— Job entry point ——


def run(dry_run: bool = False) -> dict[str, Any]:
    """Job: 从已结算比赛计算模型评估指标。

    查询条件：
      - official_matches 已结算 (Settled)
      - official_results 有比分
      - model_predictions 有预测记录
      - 尚未有对应的 market_efficiency_metrics 记录
    """
    if dry_run:
        return {"status": "dry_run", "message": "evaluation metrics (dry run)"}

    from apps.backend.src.db import get_db

    with get_db() as conn:
        cur = conn.cursor()

        # 查找待评估的预测
        cur.execute("""
            SELECT
                mp.match_id,
                mp.model_version_id,
                mp.predict_time,
                mp.model_probability,
                mp.market_probability,
                mp.option_code,
                mv.model_name,
                CASE
                    WHEN r.full_home_goals > r.full_away_goals THEN '3'
                    WHEN r.full_home_goals = r.full_away_goals THEN '1'
                    ELSE '0'
                END AS actual_result
            FROM model_predictions mp
            JOIN model_versions mv ON mv.id = mp.model_version_id
            JOIN official_results r ON r.match_id = mp.match_id
            JOIN official_matches m ON m.id = mp.match_id
            WHERE m.match_status = 'Settled'
              AND r.full_home_goals IS NOT NULL
              AND r.result_status IN ('final', 'confirmed')
              AND mp.play_type = 'spf'
              AND mp.option_code IN ('3', '1', '0')
              AND mp.predict_time < m.kickoff_time
              AND mp.validation_status = 'valid'
              AND COALESCE(
                  (mp.uncertainty_reason->>'model_independent')::boolean,
                  false
              ) = true
              AND NOT EXISTS (
                  SELECT 1 FROM market_efficiency_metrics mem
                  WHERE mem.match_id = mp.match_id
                    AND mem.model_version_id = mp.model_version_id
                    AND mem.snapshot_time = mp.predict_time
              )
            ORDER BY mp.match_id, mp.model_version_id, mp.option_code
        """)
        rows = cur.fetchall()

        if not rows:
            return {"status": "ok", "evaluated": 0, "note": "no new predictions to evaluate"}

        # 按 (match_id, model_version_id, predict_time) 分组
        from collections import defaultdict as dd

        groups: dict[tuple, dict] = dd(lambda: {"probs": {}, "market_probs": {}, "actual": None})

        for row in rows:
            match_id, mv_id, pred_time, model_p, market_p, opt_code, model_name, actual = row
            key = (match_id, mv_id, str(pred_time))

            g = groups[key]
            g["match_id"] = match_id
            g["model_version_id"] = mv_id
            g["predict_time"] = str(pred_time)
            g["model_name"] = model_name
            g["probs"][opt_code] = float(model_p)
            g["market_probs"][opt_code] = float(market_p)
            g["actual"] = actual

        # 计算指标
        metrics_list = []
        model_stats: dict[str, dict] = dd(
            lambda: {"brier": [], "log_loss": [], "rps": [], "count": 0}
        )

        for _key, g in groups.items():
            if len(g["probs"]) < 3 or g["actual"] is None:
                continue

            m = compute_match_metrics(
                g["probs"],
                g["market_probs"],
                g["actual"],
                g.get("model_name", "unknown"),
            )
            m["match_id"] = g["match_id"]
            m["model_version_id"] = g["model_version_id"]
            m["predict_time"] = g["predict_time"]
            m["play_type"] = "spf"
            m["option_code"] = g.get("actual", "3")

            metrics_list.append(m)

            mn = g.get("model_name", "unknown")
            model_stats[mn]["brier"].append(m["brier_score"])
            model_stats[mn]["log_loss"].append(m["log_loss"])
            model_stats[mn]["rps"].append(m["rps"])
            model_stats[mn]["count"] += 1

        # 汇总
        summary = {}
        for mn, stats in model_stats.items():
            n = stats["count"]
            summary[mn] = {
                "count": n,
                "avg_brier": round(sum(stats["brier"]) / n, 4) if n > 0 else None,
                "avg_log_loss": round(sum(stats["log_loss"]) / n, 4) if n > 0 else None,
                "avg_rps": round(sum(stats["rps"]) / n, 4) if n > 0 else None,
            }

        # 存储到 DB
        stored = store_evaluation_metrics(conn, metrics_list) if metrics_list else 0

        return {
            "status": "ok",
            "evaluated": len(metrics_list),
            "stored": stored,
            "model_count": len(model_stats),
            "summary": summary,
        }


# —— 自测 ——

if __name__ == "__main__":
    print("=== 评估指标测试 ===\n")

    # 测试数据：模型预测主胜 0.45、平局 0.25、客胜 0.30，实际主胜
    probs = {"3": 0.45, "1": 0.25, "0": 0.30}
    market_probs = {"3": 0.42, "1": 0.28, "0": 0.30}
    actual = "3"

    bs = brier_score(probs, actual)
    ll = log_loss_score(probs, actual)
    rps = rps_score(probs, actual)
    clv_h = clv(probs["3"], market_probs["3"])

    print(f"Brier Score:  {bs:.4f}")
    print(f"Log Loss:     {ll:.4f}")
    print(f"RPS:          {rps:.4f}")
    print(f"CLV (主胜):    {clv_h:.4f}")

    # 验证完美预测
    perfect = brier_score({"3": 1.0, "1": 0.0, "0": 0.0}, "3")
    print(f"\n完美预测 Brier: {perfect:.4f} (应 = 0.0)")
    assert perfect < 0.001

    # 验证不如随机
    bad = brier_score({"3": 0.20, "1": 0.60, "0": 0.20}, "3")
    print(f"糟糕预测 Brier: {bad:.4f} (应 > {bs:.4f})")
    assert bad > bs

    # 校准测试
    cal_preds = [
        (0.1, 0),
        (0.2, 0),
        (0.3, 1),
        (0.4, 0),
        (0.5, 1),
        (0.6, 1),
        (0.7, 1),
        (0.8, 1),
        (0.85, 1),
        (0.95, 1),
    ]
    cal = compute_calibration(cal_preds, n_bins=5)
    print(f"\nECE (Expected Calibration Error): {cal['ece']:.4f}")

    print("\n✅ 所有评估指标测试通过")
