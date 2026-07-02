"""特征重要性与 SHAP 可解释性分析。

在 match_feature_snapshots 上训练 XGBoost 影子分类器，
计算排列重要性 + SHAP 值，支持：
  1. 特征重要性排名（gain + permutation）
  2. 单预测 SHAP 瀑布图数据
  3. 按联赛/条件分段的特征表现

用法：
  from scripts.feature_importance import (
      train_if_needed,
      get_feature_importance,
      explain_prediction,
      get_model_comparison_data,
  )
"""

from __future__ import annotations

import os
import sys
from typing import Any

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Feature column definitions — must match match_feature_snapshots table
# ---------------------------------------------------------------------------

# Numeric features extracted from the 49-column snapshot
FEATURE_COLUMNS: list[str] = [
    "home_team_market_value",
    "away_team_market_value",
    "team_market_value_ratio",
    "home_attack_strength_score",
    "away_attack_strength_score",
    "home_defense_strength_score",
    "away_defense_strength_score",
    "home_lineup_confirmed",
    "away_lineup_confirmed",
    "home_starting_11_value",
    "away_starting_11_value",
    "starting_11_value_diff",
    "home_lineup_strength_score",
    "away_lineup_strength_score",
    "lineup_strength_diff",
    "home_absence_impact_score",
    "away_absence_impact_score",
    "absence_impact_diff",
    "home_key_absence_count",
    "away_key_absence_count",
    "home_rotation_risk_score",
    "away_rotation_risk_score",
    "rotation_risk_diff",
    "home_rest_days",
    "away_rest_days",
    "rest_days_diff",
    "away_travel_distance_km",
    "timezone_diff",
    "altitude_m",
    "away_travel_fatigue_score",
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_impact_score",
    "goal_expectation_weather_adjustment",
    "home_motivation_score",
    "away_motivation_score",
    "motivation_diff",
    "home_must_win",
    "away_must_win",
    "home_draw_enough",
    "away_draw_enough",
    "home_avoid_strong_opponent_score",
    "away_avoid_strong_opponent_score",
    "home_tanking_risk_score",
    "away_tanking_risk_score",
    "tournament_incentive_risk_score",
    "data_completeness_score",
    "source_confidence_score",
    "uncertainty_score",
]

# Chinese labels for display
FEATURE_LABELS: dict[str, str] = {
    "home_team_market_value": "主队市场价值(概率)",
    "away_team_market_value": "客队市场价值(概率)",
    "team_market_value_ratio": "市场价值比",
    "home_attack_strength_score": "主队进攻强度",
    "away_attack_strength_score": "客队进攻强度",
    "home_defense_strength_score": "主队防守强度",
    "away_defense_strength_score": "客队防守强度",
    "home_lineup_confirmed": "主队首发确认",
    "away_lineup_confirmed": "客队首发确认",
    "home_starting_11_value": "主队首发身价",
    "away_starting_11_value": "客队首发身价",
    "starting_11_value_diff": "首发身价差",
    "home_lineup_strength_score": "主队阵容强度",
    "away_lineup_strength_score": "客队阵容强度",
    "lineup_strength_diff": "阵容强度差",
    "home_absence_impact_score": "主队缺阵影响",
    "away_absence_impact_score": "客队缺阵影响",
    "absence_impact_diff": "缺阵影响差",
    "home_key_absence_count": "主队关键缺阵数",
    "away_key_absence_count": "客队关键缺阵数",
    "home_rotation_risk_score": "主队轮换风险",
    "away_rotation_risk_score": "客队轮换风险",
    "rotation_risk_diff": "轮换风险差",
    "home_rest_days": "主队休息天数",
    "away_rest_days": "客队休息天数",
    "rest_days_diff": "休息天数差",
    "away_travel_distance_km": "客场旅行距离(km)",
    "timezone_diff": "时区差",
    "altitude_m": "海拔(m)",
    "away_travel_fatigue_score": "客场旅行疲劳",
    "temperature_2m": "温度(°C)",
    "precipitation": "降水量",
    "wind_speed_10m": "风速",
    "weather_impact_score": "天气影响",
    "goal_expectation_weather_adjustment": "进球预期天气修正",
    "home_motivation_score": "主队战意",
    "away_motivation_score": "客队战意",
    "motivation_diff": "战意差",
    "home_must_win": "主队必须赢",
    "away_must_win": "客队必须赢",
    "home_draw_enough": "主队平局足够",
    "away_draw_enough": "客队平局足够",
    "home_avoid_strong_opponent_score": "主队避强敌",
    "away_avoid_strong_opponent_score": "客队避强敌",
    "home_tanking_risk_score": "主队摆烂风险",
    "away_tanking_risk_score": "客队摆烂风险",
    "tournament_incentive_risk_score": "赛事激励风险",
    "data_completeness_score": "数据完整度",
    "source_confidence_score": "数据源置信度",
    "uncertainty_score": "不确定性",
}


def _label(name: str) -> str:
    return FEATURE_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_training_data(
    conn: Any,
    min_samples: int = 50,
) -> tuple[np.ndarray, np.ndarray, list[int], list[str]] | None:
    """从 match_feature_snapshots + official_results 构建训练集。

    Returns:
        (X, y, match_ids, feature_names) or None if insufficient data.
        y in {0, 1, 2} = {客胜, 平局, 主胜}
    """
    col_refs = ", ".join(f"fs.{c}" for c in FEATURE_COLUMNS)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT
                fs.match_id,
                fs.league_name,
                {col_refs},
                CASE
                    WHEN r.home_goals > r.away_goals THEN 2
                    WHEN r.home_goals = r.away_goals THEN 1
                    ELSE 0
                END AS label
            FROM match_feature_snapshots fs
            JOIN official_results r ON r.match_id = fs.match_id
            WHERE fs.feature_version IS NOT NULL
            ORDER BY fs.snapshot_time DESC
            LIMIT 5000
        """)
        rows = cur.fetchall()

    if len(rows) < min_samples:
        return None

    match_ids = [r[0] for r in rows]
    # r[1] is league_name (skip in feature matrix)
    # r[2:2+len(FEATURE_COLUMNS)] are features
    # last element is label

    n_features = len(FEATURE_COLUMNS)
    X = np.array(
        [[float(v) if v is not None else np.nan for v in r[2 : 2 + n_features]] for r in rows],
        dtype=np.float64,
    )
    y = np.array([r[-1] for r in rows], dtype=np.int64)

    # Identify which features have any non-NaN values
    valid_mask = ~np.all(np.isnan(X), axis=0)
    valid_indices = np.where(valid_mask)[0]
    X_valid = X[:, valid_indices]
    feature_names = [FEATURE_COLUMNS[i] for i in valid_indices]

    # Impute NaN with column median (or 0 if all NaN)
    for j in range(X_valid.shape[1]):
        col = X_valid[:, j]
        nan_mask = np.isnan(col)
        if nan_mask.any():
            fill_val = np.nanmedian(col) if not np.all(nan_mask) else 0.0
            col[nan_mask] = fill_val

    return X_valid, y, match_ids, feature_names


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

# Module-level cache
_trained_model: Any = None
_trained_explainer: Any = None
_feature_names_cache: list[str] = []
_importance_cache: dict[str, Any] = {}
_train_score: float = 0.0


def train_if_needed(conn: Any, force: bool = False) -> dict[str, Any]:
    """训练 XGBoost 影子分类器（如果尚未训练或 force=True）。

    Returns:
        {"status": "ok", "n_samples": int, "n_features": int,
         "train_accuracy": float, "feature_count": int}
    """
    global _trained_model, _trained_explainer, _feature_names_cache, _importance_cache, _train_score

    if _trained_model is not None and not force:
        return {
            "status": "ok",
            "cached": True,
            "n_features": len(_feature_names_cache),
            "train_accuracy": round(_train_score, 4),
            "feature_count": len(_feature_names_cache),
        }

    try:
        import xgboost as xgb
    except ImportError:
        return {"status": "error", "error": "xgboost 未安装。运行: pip install xgboost"}

    data = _load_training_data(conn)
    if data is None:
        return {"status": "error", "error": "训练数据不足（需要至少50条已结算的特征快照）"}

    X, y, _match_ids, feature_names = data

    # Train XGBoost multi-class classifier
    n_classes = 3
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=n_classes,
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)

    _trained_model = model
    _feature_names_cache = feature_names
    _train_score = float(model.score(X, y))

    # Build SHAP explainer
    try:
        _trained_explainer = _build_shap_explainer(model, X)
    except Exception:
        _trained_explainer = None

    # Compute permutation importance
    _importance_cache = _compute_permutation_importance(model, X, y, feature_names)

    return {
        "status": "ok",
        "cached": False,
        "n_samples": len(y),
        "n_features": len(feature_names),
        "train_accuracy": round(_train_score, 4),
        "feature_count": len(feature_names),
        "class_distribution": {
            "home_win": int((y == 2).sum()),
            "draw": int((y == 1).sum()),
            "away_win": int((y == 0).sum()),
        },
    }


def _build_shap_explainer(model: Any, X: np.ndarray) -> Any:
    """Build a SHAP TreeExplainer on a background sample."""
    try:
        import shap

        # Use a subset as background (max 100 samples for speed)
        bg = X[np.random.RandomState(42).choice(len(X), min(100, len(X)), replace=False)]
        explainer = shap.TreeExplainer(model, bg, feature_perturbation="interventional")
        return explainer
    except Exception:
        return None


def _compute_permutation_importance(
    model: Any,
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    n_repeats: int = 5,
) -> dict[str, Any]:
    """Compute permutation feature importance."""
    try:
        from sklearn.inspection import permutation_importance

        r = permutation_importance(
            model, X, y, n_repeats=n_repeats, random_state=42, n_jobs=-1
        )

        rankings = []
        for i, name in enumerate(feature_names):
            rankings.append(
                {
                    "feature": name,
                    "label": _label(name),
                    "importance": round(float(r.importances_mean[i]), 6),
                    "std": round(float(r.importances_std[i]), 6),
                }
            )
        rankings.sort(key=lambda x: -x["importance"])  # type: ignore[operator]

        # XGBoost native gain-based importance
        gain_importance = model.feature_importances_
        gain_rankings = []
        for i, name in enumerate(feature_names):
            gain_rankings.append(
                {
                    "feature": name,
                    "label": _label(name),
                    "importance": round(float(gain_importance[i]), 6),
                }
            )
        gain_rankings.sort(key=lambda x: -x["importance"])  # type: ignore[operator]

        return {
            "permutation": rankings,
            "gain": gain_rankings,
            "top_permutation": rankings[:15],
            "top_gain": gain_rankings[:15],
        }
    except Exception:
        return {"permutation": [], "gain": [], "top_permutation": [], "top_gain": []}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_feature_importance(
    conn: Any,
    method: str = "permutation",
    top_n: int = 20,
) -> dict[str, Any]:
    """获取特征重要性排名。

    Args:
        conn: DB 连接
        method: "permutation" | "gain" | "both"
        top_n: 返回前 N 个特征

    Returns:
        {"status": "ok", "method": str, "rankings": [...], "model_accuracy": float}
    """
    train_result = train_if_needed(conn)
    if train_result.get("status") == "error":
        return train_result

    if method == "permutation":
        rankings = _importance_cache.get("permutation", [])[:top_n]
    elif method == "gain":
        rankings = _importance_cache.get("gain", [])[:top_n]
    else:
        rankings = {
            "permutation": _importance_cache.get("permutation", [])[:top_n],
            "gain": _importance_cache.get("gain", [])[:top_n],
        }

    return {
        "status": "ok",
        "method": method,
        "rankings": rankings,
        "model_accuracy": round(_train_score, 4),
        "n_features": len(_feature_names_cache),
    }


def explain_prediction(
    conn: Any,
    match_id: int,
    top_n: int = 15,
) -> dict[str, Any]:
    """为单场比赛提供 SHAP 解释。

    Args:
        conn: DB 连接
        match_id: 比赛 ID
        top_n: 返回前 N 个重要特征

    Returns:
        {"status": "ok", "match_id": int, "shap_values": [...],
         "base_value": float, "predicted_probs": [float, float, float]}
    """
    global _trained_model, _trained_explainer, _feature_names_cache

    # Ensure model is trained
    train_result = train_if_needed(conn)
    if train_result.get("status") == "error":
        return train_result

    # Load feature row for this match
    col_refs = ", ".join(f"fs.{c}" for c in FEATURE_COLUMNS)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT
                fs.match_id,
                fs.home_team_name,
                fs.away_team_name,
                {col_refs}
            FROM match_feature_snapshots fs
            WHERE fs.match_id = %s
            ORDER BY fs.snapshot_time DESC
            LIMIT 1
        """, (match_id,))
        row = cur.fetchone()

    if not row:
        return {"status": "error", "error": f"未找到比赛 {match_id} 的特征快照"}

    home_team = row[1] or ""
    away_team = row[2] or ""
    raw_features = row[3:]

    # Build feature vector matching training columns
    full_vec = np.array(
        [float(v) if v is not None else np.nan for v in raw_features], dtype=np.float64
    )

    # Map to training feature subset
    train_indices = [FEATURE_COLUMNS.index(f) for f in _feature_names_cache]
    X_single = full_vec[train_indices].reshape(1, -1)

    # Impute NaN
    for j in range(X_single.shape[1]):
        if np.isnan(X_single[0, j]):
            X_single[0, j] = 0.0

    # Predict
    probs = _trained_model.predict_proba(X_single)[0]  # [away, draw, home]

    # SHAP values
    shap_data: list[dict[str, Any]] = []
    base_values: list[float] = [0.33, 0.34, 0.33]

    if _trained_explainer is not None:
        try:
            shap_vals = _trained_explainer(X_single)  # shape: (1, n_features, n_classes)
            # shap_vals.values shape: (1, n_features, n_classes)
            raw_values = shap_vals.values[0]  # (n_features, n_classes)

            # For multi-class, aggregate absolute SHAP across classes
            agg_shap = np.abs(raw_values).sum(axis=1)  # shape: (n_features,)

            base_values = shap_vals.base_values[0].tolist()  # (n_classes,)

            # Build per-feature SHAP data for waterfall (class 2 = home win)
            for j in range(len(_feature_names_cache)):
                shap_data.append(
                    {
                        "feature": _feature_names_cache[j],
                        "label": _label(_feature_names_cache[j]),
                        "shap_value": round(float(raw_values[j, 2]), 6),  # home-win class
                        "shap_abs": round(float(agg_shap[j]), 6),
                        "feature_value": round(float(X_single[0, j]), 4),
                    }
                )
            shap_data.sort(key=lambda x: -x["shap_abs"])
            shap_data = shap_data[:top_n]

            # Re-sort by shap_value for waterfall display
            shap_data.sort(key=lambda x: x["shap_value"])
        except Exception:
            shap_data = []

    return {
        "status": "ok",
        "match_id": match_id,
        "home_team": home_team,
        "away_team": away_team,
        "predicted_probs": {
            "home": round(float(probs[2]), 4),
            "draw": round(float(probs[1]), 4),
            "away": round(float(probs[0]), 4),
        },
        "base_values": [round(float(b), 4) for b in base_values],
        "shap_values": shap_data,
        "n_features_used": len(_feature_names_cache),
    }


def get_model_comparison_data(conn: Any) -> dict[str, Any]:
    """获取模型对比数据（用于雷达图）。

    从 market_efficiency_metrics + backtest 数据聚合各模型指标。

    Returns:
        {"status": "ok", "models": [{"name": str, "brier": float, ...}, ...]}
    """
    models_data: dict[str, dict[str, Any]] = {}

    # 1. Evaluation metrics from market_efficiency_metrics
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                mv.model_name,
                COUNT(*) AS n_predictions,
                AVG(mem.brier_score) AS avg_brier,
                AVG(mem.log_loss) AS avg_log_loss,
                AVG(mem.rps) AS avg_rps,
                AVG(mem.clv_score) AS avg_clv,
                AVG(mem.favourite_longshot_score) AS avg_flb_score
            FROM market_efficiency_metrics mem
            JOIN model_versions mv ON mv.id = mem.model_version_id
            WHERE mem.brier_score IS NOT NULL
            GROUP BY mv.model_name
            ORDER BY mv.model_name
        """)
        columns = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            name = d["model_name"]
            models_data[name] = {
                "name": name,
                "n_predictions": int(d["n_predictions"] or 0),
                "brier": round(float(d["avg_brier"] or 0), 4),
                "log_loss": round(float(d["avg_log_loss"] or 0), 4),
                "rps": round(float(d["avg_rps"] or 0), 4),
                "clv": round(float(d["avg_clv"] or 0), 4),
                "flb_score": round(float(d["avg_flb_score"] or 0), 4),
            }

    # 2. Backtest performance (latest aggregate)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                brr.model_name,
                brr.hit_rate,
                brr.roi,
                brr.sharpe_ratio,
                brr.max_drawdown_pct,
                brr.profit_factor,
                brr.total_profit
            FROM backtest_run_results brr
            JOIN backtest_runs br ON br.id = brr.run_id
            WHERE brr.window_index IS NULL
              AND br.status = 'completed'
            ORDER BY br.created_at DESC
        """)
        columns = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            name = d["model_name"]
            if name in models_data:
                models_data[name].update(
                    {
                        "hit_rate": round(float(d["hit_rate"] or 0), 4),
                        "roi": round(float(d["roi"] or 0), 4),
                        "sharpe": round(float(d["sharpe_ratio"] or 0), 4),
                        "max_drawdown_pct": round(float(d["max_drawdown_pct"] or 0), 4),
                        "profit_factor": round(float(d["profit_factor"] or 0), 4),
                        "total_profit": round(float(d["total_profit"] or 0), 2),
                    }
                )

    models_list = list(models_data.values())
    models_list.sort(key=lambda m: m.get("roi", -999), reverse=True)

    return {
        "status": "ok",
        "models": models_list,
        "total_models": len(models_list),
        # Radar chart dimensions
        "radar_dimensions": [
            {"key": "brier_inv", "label": "Brier (越低越好)", "invert": True},
            {"key": "log_loss_inv", "label": "LogLoss (越低越好)", "invert": True},
            {"key": "roi", "label": "ROI"},
            {"key": "sharpe", "label": "夏普比率"},
            {"key": "hit_rate", "label": "胜率"},
            {"key": "profit_factor", "label": "盈利因子"},
        ],
    }


def get_evaluation_summary(conn: Any) -> dict[str, Any]:
    """获取模型评估摘要（Brier/LogLoss/RPS per model + 整体统计）。

    Returns:
        {"status": "ok", "models": [...], "overall": {...}}
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                mv.model_name,
                COUNT(*) AS n,
                ROUND(AVG(mem.brier_score)::numeric, 4) AS avg_brier,
                ROUND(AVG(mem.log_loss)::numeric, 4) AS avg_logloss,
                ROUND(AVG(mem.rps)::numeric, 4) AS avg_rps,
                ROUND(AVG(mem.clv_score)::numeric, 4) AS avg_clv
            FROM market_efficiency_metrics mem
            JOIN model_versions mv ON mv.id = mem.model_version_id
            WHERE mem.brier_score IS NOT NULL
            GROUP BY mv.model_name
            ORDER BY avg_brier ASC
        """)
        columns = [desc[0] for desc in cur.description]
        models = []
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            models.append(
                {
                    "model_name": d["model_name"],
                    "n": int(d["n"]),
                    "avg_brier": float(d["avg_brier"] or 0),
                    "avg_logloss": float(d["avg_logloss"] or 0),
                    "avg_rps": float(d["avg_rps"] or 0),
                    "avg_clv": float(d["avg_clv"] or 0),
                }
            )

        # Overall stats
        cur.execute("""
            SELECT
                COUNT(*) AS total_evaluated,
                ROUND(AVG(brier_score)::numeric, 4) AS overall_brier,
                ROUND(AVG(log_loss)::numeric, 4) AS overall_logloss
            FROM market_efficiency_metrics
            WHERE brier_score IS NOT NULL
        """)
        overall_row = cur.fetchone()
        overall = {
            "total_evaluated": int(overall_row[0] or 0),
            "overall_brier": float(overall_row[1] or 0),
            "overall_logloss": float(overall_row[2] or 0),
        }

    return {"status": "ok", "models": models, "overall": overall}


def get_calibration_data(
    conn: Any,
    model_name: str | None = None,
    n_bins: int = 10,
) -> dict[str, Any]:
    """获取校准曲线数据。

    Args:
        conn: DB 连接
        model_name: 模型名称（None = 所有模型聚合）
        n_bins: 分箱数

    Returns:
        {"status": "ok", "model_name": str, "bins": [...], "ece": float, "mce": float}
    """
    from scripts.evaluation_metrics import compute_calibration

    with conn.cursor() as cur:
        if model_name:
            cur.execute("""
                SELECT
                    mp.model_probability,
                    CASE
                        WHEN r.home_goals > r.away_goals AND mp.option_code = '3' THEN 1
                        WHEN r.home_goals = r.away_goals AND mp.option_code = '1' THEN 1
                        WHEN r.home_goals < r.away_goals AND mp.option_code = '0' THEN 1
                        ELSE 0
                    END AS is_correct
                FROM model_predictions mp
                JOIN model_versions mv ON mv.id = mp.model_version_id
                JOIN official_results r ON r.match_id = mp.match_id
                WHERE mv.model_name = %s
                  AND mp.play_type = 'spf'
                  AND mp.model_probability IS NOT NULL
                ORDER BY mp.predict_time DESC
                LIMIT 2000
            """, (model_name,))
        else:
            cur.execute("""
                SELECT
                    mp.model_probability,
                    CASE
                        WHEN r.home_goals > r.away_goals AND mp.option_code = '3' THEN 1
                        WHEN r.home_goals = r.away_goals AND mp.option_code = '1' THEN 1
                        WHEN r.home_goals < r.away_goals AND mp.option_code = '0' THEN 1
                        ELSE 0
                    END AS is_correct
                FROM model_predictions mp
                JOIN official_results r ON r.match_id = mp.match_id
                WHERE mp.play_type = 'spf'
                  AND mp.model_probability IS NOT NULL
                ORDER BY mp.predict_time DESC
                LIMIT 5000
            """)

        predictions = [
            (float(row[0]), int(row[1])) for row in cur.fetchall()
        ]

    if len(predictions) < n_bins:
        return {
            "status": "ok",
            "model_name": model_name or "all",
            "bins": [],
            "ece": 0.0,
            "mce": 0.0,
            "n_predictions": len(predictions),
            "note": "insufficient data",
        }

    cal = compute_calibration(predictions, n_bins=n_bins)

    return {
        "status": "ok",
        "model_name": model_name or "all",
        "bins": cal["bins"],
        "ece": cal["ece"],
        "mce": cal["mce"],
        "n_predictions": len(predictions),
    }


def get_condition_performance(
    conn: Any,
    dimension: str = "league",
) -> dict[str, Any]:
    """按条件（联赛/赔率区间/信心度）分段的模型表现。

    Args:
        conn: DB 连接
        dimension: "league" | "odds_range" | "confidence"

    Returns:
        {"status": "ok", "dimension": str, "segments": [...]}
    """
    if dimension == "league":
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.league_name,
                    mv.model_name,
                    COUNT(*) AS n,
                    ROUND(AVG(mem.brier_score)::numeric, 4) AS avg_brier,
                    ROUND(AVG(mem.log_loss)::numeric, 4) AS avg_logloss
                FROM market_efficiency_metrics mem
                JOIN model_versions mv ON mv.id = mem.model_version_id
                JOIN official_matches m ON m.id = mem.match_id
                WHERE mem.brier_score IS NOT NULL
                  AND m.league_name IS NOT NULL
                GROUP BY m.league_name, mv.model_name
                HAVING COUNT(*) >= 5
                ORDER BY m.league_name, avg_brier ASC
            """)
            columns = [desc[0] for desc in cur.description]
            segments = [dict(zip(columns, row)) for row in cur.fetchall()]

    elif dimension == "odds_range":
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN mp.market_probability < 0.30 THEN '低概率 (<30%)'
                        WHEN mp.market_probability < 0.45 THEN '中低概率 (30-45%)'
                        WHEN mp.market_probability < 0.55 THEN '中概率 (45-55%)'
                        WHEN mp.market_probability < 0.70 THEN '中高概率 (55-70%)'
                        ELSE '高概率 (>70%)'
                    END AS odds_range,
                    mv.model_name,
                    COUNT(*) AS n,
                    ROUND(AVG(mem.brier_score)::numeric, 4) AS avg_brier
                FROM market_efficiency_metrics mem
                JOIN model_versions mv ON mv.id = mem.model_version_id
                JOIN model_predictions mp
                    ON mp.match_id = mem.match_id
                    AND mp.model_version_id = mem.model_version_id
                    AND mp.option_code = '3'
                WHERE mem.brier_score IS NOT NULL
                GROUP BY odds_range, mv.model_name
                HAVING COUNT(*) >= 3
                ORDER BY odds_range, avg_brier ASC
            """)
            columns = [desc[0] for desc in cur.description]
            segments = [dict(zip(columns, row)) for row in cur.fetchall()]

    elif dimension == "confidence":
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN mp.confidence_score < 0.3 THEN '低信心 (<30%)'
                        WHEN mp.confidence_score < 0.5 THEN '中低信心 (30-50%)'
                        WHEN mp.confidence_score < 0.7 THEN '中高信心 (50-70%)'
                        ELSE '高信心 (>70%)'
                    END AS confidence_range,
                    mv.model_name,
                    COUNT(*) AS n,
                    ROUND(AVG(mem.brier_score)::numeric, 4) AS avg_brier
                FROM market_efficiency_metrics mem
                JOIN model_versions mv ON mv.id = mem.model_version_id
                JOIN model_predictions mp
                    ON mp.match_id = mem.match_id
                    AND mp.model_version_id = mem.model_version_id
                    AND mp.option_code = '3'
                WHERE mem.brier_score IS NOT NULL
                GROUP BY confidence_range, mv.model_name
                HAVING COUNT(*) >= 3
                ORDER BY confidence_range, avg_brier ASC
            """)
            columns = [desc[0] for desc in cur.description]
            segments = [dict(zip(columns, row)) for row in cur.fetchall()]
    else:
        return {"status": "error", "error": f"未知维度: {dimension}"}

    # Convert to serializable
    result_segments = []
    for s in segments:
        result_segments.append(
            {k: (float(v) if isinstance(v, (float, int)) and k != "n" else v) for k, v in s.items()}
        )

    return {"status": "ok", "dimension": dimension, "segments": result_segments}
