"""分析仪表盘 API 端点 (Batch 5)。

提供模型评估、特征重要性、SHAP 可解释性、模型对比等分析接口。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from apps.backend.src.db import get_db
from scripts.feature_importance import (
    explain_prediction,
    get_calibration_data,
    get_condition_performance,
    get_evaluation_summary,
    get_feature_importance,
    get_model_comparison_data,
    recommend_best_combos,
    train_if_needed,
)

router = APIRouter(tags=["analysis"])


# ---------------------------------------------------------------------------
# 模型评估
# ---------------------------------------------------------------------------


@router.get("/api/analysis/evaluation/summary")
def evaluation_summary():
    """获取所有模型的评估指标摘要（Brier / LogLoss / RPS / CLV）。

    数据来源：market_efficiency_metrics 表。
    """
    with get_db() as conn:
        return get_evaluation_summary(conn)


@router.get("/api/analysis/evaluation/calibration")
def calibration_curve(
    model_name: Optional[str] = Query(  # noqa: UP045
        None, description="模型名称（不传则返回所有模型聚合校准曲线）"
    ),
    n_bins: int = Query(10, ge=5, le=20, description="分箱数"),
):
    """获取模型校准曲线数据（预测概率 vs 实际频率）。

    返回 ECE (Expected Calibration Error) 和 MCE (Max Calibration Error)。
    """
    with get_db() as conn:
        return get_calibration_data(conn, model_name=model_name, n_bins=n_bins)


@router.get("/api/analysis/evaluation/by-condition")
def condition_performance(
    dimension: str = Query("league", description="分组维度：league | odds_range | confidence"),
):
    """按条件（联赛/赔率区间/信心度）分段的模型表现。

    用于发现模型在特定条件下的优劣势。
    """
    if dimension not in ("league", "odds_range", "confidence"):
        raise HTTPException(400, "dimension must be league | odds_range | confidence")

    with get_db() as conn:
        return get_condition_performance(conn, dimension=dimension)


@router.get("/api/analysis/recommendations")
def get_recommendations(
    min_samples: int = Query(5, description="最低结算样本数"),
    top_n: int = Query(15, description="返回 Top N 组合"),
):
    """推荐最佳 模型×玩法 组合，按命中率降序排列。

    从已结算比赛的实际结果中统计每个 (model_name, play_type)
    的正确率，返回 TOP N 推荐。
    """
    with get_db() as conn:
        combos = recommend_best_combos(conn, min_samples=min_samples, top_n=top_n)
    return {"status": "ok", "recommendations": combos}


# ---------------------------------------------------------------------------
# 模型对比
# ---------------------------------------------------------------------------


@router.get("/api/analysis/models/compare")
def model_comparison():
    """获取多模型横向对比数据（用于雷达图 + 排名表）。

    聚合 market_efficiency_metrics + backtest_run_results 两大数据源，
    返回 Brier、LogLoss、ROI、夏普比率、胜率、盈利因子等指标。
    """
    with get_db() as conn:
        return get_model_comparison_data(conn)


# ---------------------------------------------------------------------------
# 特征重要性
# ---------------------------------------------------------------------------


@router.get("/api/analysis/features/importance")
def feature_importance(
    method: str = Query("permutation", description="方法：permutation | gain | both"),
    top_n: int = Query(20, ge=5, le=50, description="返回前 N 个特征"),
    force_retrain: bool = Query(False, description="强制重新训练 XGBoost 模型"),
):
    """获取特征重要性排名。

    在 match_feature_snapshots 上训练 XGBoost 影子分类器，
    计算排列重要性（permutation）和增益重要性（gain）。

    首次调用自动训练并缓存模型。
    """
    if method not in ("permutation", "gain", "both"):
        raise HTTPException(400, "method must be permutation | gain | both")

    with get_db() as conn:
        # Trigger training if needed
        train_result = train_if_needed(conn, force=force_retrain)
        if train_result.get("status") == "error":
            return train_result

        return get_feature_importance(conn, method=method, top_n=top_n)


@router.get("/api/analysis/features/model-info")
def feature_model_info():
    """获取特征分析模型的元信息（样本数、特征数、训练准确率等）。"""
    with get_db() as conn:
        result = train_if_needed(conn)
        return result


# ---------------------------------------------------------------------------
# SHAP 可解释性
# ---------------------------------------------------------------------------


@router.get("/api/analysis/explain/{match_id}")
def shap_explanation(
    match_id: int,
    top_n: int = Query(15, ge=5, le=30, description="返回前 N 个重要特征"),
):
    """为单场比赛提供 SHAP 特征贡献解释。

    返回每个特征对预测结果的贡献值（正=提升主胜概率，负=降低主胜概率），
    以及模型预测的三个结果概率。
    """
    with get_db() as conn:
        result = explain_prediction(conn, match_id, top_n=top_n)
        if result.get("status") == "error":
            raise HTTPException(400, result.get("error", "SHAP 解释失败"))
        return result
