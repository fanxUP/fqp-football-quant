"""Single source of truth for prediction-model metadata exposed to the UI."""

from __future__ import annotations

from typing import TypedDict

CATALOG_VERSION = "2026-08-12"


class LocalizedText(TypedDict):
    zh_CN: str
    en: str


class ModelMetadata(TypedDict):
    title: LocalizedText
    summary: LocalizedText
    output: LocalizedText
    cadence: LocalizedText
    condition: LocalizedText
    role: LocalizedText
    stage: str


def _text(zh: str, en: str) -> LocalizedText:
    return {"zh_CN": zh, "en": en}


def _model(
    title: tuple[str, str],
    summary: tuple[str, str],
    output: tuple[str, str],
    cadence: tuple[str, str],
    condition: tuple[str, str],
    role: tuple[str, str],
    stage: str,
) -> ModelMetadata:
    return {
        "title": _text(*title),
        "summary": _text(*summary),
        "output": _text(*output),
        "cadence": _text(*cadence),
        "condition": _text(*condition),
        "role": _text(*role),
        "stage": stage,
    }


BASE_OUTPUT = ("胜平负概率。", "1X2 probabilities.")
SHADOW_ROLE = (
    "影子验证，不参与推荐、投注或风控。",
    "Shadow evaluation only; excluded from recommendations, betting and risk control.",
)
FEATURE_CADENCE = ("每日在官方结算后重新训练。", "Retrained daily after official settlement.")
FEATURE_CONDITION = (
    "至少 100 场训练样本和 25 场后续留出验证样本。",
    "Requires at least 100 training matches and 25 later holdout matches.",
)


MODEL_CATALOG: dict[str, ModelMetadata] = {
    "market_baseline": _model(
        ("市场赔率基准", "Market odds baseline"),
        (
            "把体彩官方赔率换算为市场隐含胜平负概率。",
            "Converts official Sporttery odds into implied 1X2 probabilities.",
        ),
        ("胜平负及市场派生概率。", "1X2 and market-derived probabilities."),
        ("随官方赔率快照更新。", "Updates with official odds snapshots."),
        ("需要完整、在售的官方赔率。", "Requires complete official odds on sale."),
        ("市场参照，不作为独立信号。", "Market reference, not an independent signal."),
        "baseline",
    ),
    "elo_rating": _model(
        ("Elo 实力评分", "Elo strength rating"),
        (
            "根据已结算赛果更新球队长期实力，并计入主场因素。",
            "Updates long-term team strength from settled results with home advantage.",
        ),
        BASE_OUTPUT,
        ("每日按新结算赛果更新。", "Updates daily from newly settled results."),
        ("双方各至少 5 场有效历史。", "Requires at least five valid matches per team."),
        ("长期实力信号。", "Long-term strength signal."),
        "production",
    ),
    "maher_poisson": _model(
        ("Maher Poisson 进球模型", "Maher Poisson goal model"),
        (
            "拟合球队进攻、防守、联赛进球和主场优势。",
            "Fits attack, defence, league scoring and home advantage.",
        ),
        (
            "胜平负、比分、总进球和半全场概率。",
            "1X2, score, total-goals and half/full-time probabilities.",
        ),
        ("每周重训。", "Retrained weekly."),
        ("需要足够历史赛果。", "Requires sufficient result history."),
        ("可解释的比分分布基础模型。", "Interpretable base score-distribution model."),
        "production",
    ),
    "dixon_coles": _model(
        ("Dixon-Coles 比分模型", "Dixon-Coles score model"),
        (
            "修正 Poisson 在低比分与平局附近的相关性。",
            "Corrects Poisson dependence around low scores and draws.",
        ),
        (
            "胜平负、比分、总进球和半全场概率。",
            "1X2, score, total-goals and half/full-time probabilities.",
        ),
        ("随 Maher Poisson 同步更新。", "Updates with the Maher Poisson model."),
        ("依赖有效预期进球和低比分样本。", "Requires valid expected goals and low-score samples."),
        ("低比分校正模型。", "Low-score correction model."),
        "production",
    ),
    "glicko2_rating": _model(
        ("Glicko-2 强度评级", "Glicko-2 strength rating"),
        (
            "同时估计球队实力、评分偏差和波动率。",
            "Estimates team strength, rating deviation and volatility.",
        ),
        BASE_OUTPUT,
        ("每日更新。", "Updates daily."),
        ("双方各至少 8 场历史。", "Requires at least eight matches per team."),
        SHADOW_ROLE,
        "shadow",
    ),
    "bivariate_poisson": _model(
        ("双变量 Poisson 进球模型", "Bivariate Poisson goal model"),
        (
            "加入共享进球成分以刻画双方比分相关性。",
            "Adds a shared-goal component to model score correlation.",
        ),
        BASE_OUTPUT,
        ("每周重估。", "Refitted weekly."),
        ("依赖已收敛的 Poisson 参数。", "Requires converged Poisson parameters."),
        SHADOW_ROLE,
        "shadow",
    ),
    "xgboost_shadow": _model(
        ("XGBoost 赛前特征模型", "XGBoost pre-match model"),
        (
            "学习赛前结构化特征的非线性关系。",
            "Learns nonlinear relations among structured pre-match features.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "logistic_shadow": _model(
        ("Logistic Regression 赛前模型", "Logistic Regression pre-match model"),
        (
            "用正则化线性组合提供可解释概率基准。",
            "Provides an interpretable regularized linear probability baseline.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "bayesian_form": _model(
        ("Bayesian 近期状态模型", "Bayesian recent-form model"),
        (
            "对近期赛果作 Bayesian 收缩，抑制小样本极端值。",
            "Shrinks recent results to reduce small-sample extremes.",
        ),
        BASE_OUTPUT,
        ("每次赛前读取最新已结算赛果。", "Reads the latest settled results before each match."),
        ("双方各至少 6 场历史。", "Requires at least six matches per team."),
        SHADOW_ROLE,
        "shadow",
    ),
    "random_forest_shadow": _model(
        ("Random Forest 赛前模型", "Random Forest pre-match model"),
        (
            "用多棵决策树学习赛前特征交互。",
            "Learns pre-match feature interactions with an ensemble of trees.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "extra_trees_shadow": _model(
        ("Extra Trees 赛前模型", "Extra Trees pre-match model"),
        (
            "用随机分裂检验树模型信号的稳健性。",
            "Uses randomized splits to test tree-signal robustness.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "hist_gradient_boosting_shadow": _model(
        ("Histogram Gradient Boosting 赛前模型", "Histogram Gradient Boosting pre-match model"),
        (
            "用直方图近似学习非线性赛前信号。",
            "Uses histogram approximation for nonlinear pre-match signals.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "adaboost_shadow": _model(
        ("AdaBoost 赛前模型", "AdaBoost pre-match model"),
        (
            "逐轮关注难分类样本，组合弱学习器。",
            "Combines weak learners while focusing on difficult samples.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "lda_shadow": _model(
        ("LDA 赛前模型", "LDA pre-match model"),
        (
            "以正则化类别分布提供线性判别基准。",
            "Provides a linear discriminant baseline from regularized class distributions.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "knn_shadow": _model(
        ("KNN 近邻赛前模型", "KNN pre-match model"),
        ("按特征距离寻找历史相似比赛。", "Finds historically similar matches by feature distance."),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "mlp_shadow": _model(
        ("MLP 赛前模型", "MLP pre-match model"),
        (
            "用轻量多层感知机学习非线性特征交互。",
            "Uses a lightweight multilayer perceptron for nonlinear interactions.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "naive_bayes_shadow": _model(
        ("Naive Bayes 赛前模型", "Naive Bayes pre-match model"),
        (
            "用条件分布形成轻量概率基准。",
            "Forms a lightweight probability baseline from conditional distributions.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "svm_shadow": _model(
        ("SVM 赛前模型", "SVM pre-match model"),
        (
            "用 RBF 边界识别局部非线性模式并校准概率。",
            "Uses an RBF boundary for local nonlinear patterns with calibrated probabilities.",
        ),
        BASE_OUTPUT,
        FEATURE_CADENCE,
        FEATURE_CONDITION,
        SHADOW_ROLE,
        "shadow",
    ),
    "negative_binomial_shadow": _model(
        ("负二项进球模型", "Negative Binomial goal model"),
        (
            "允许进球数高于 Poisson 假设的离散度。",
            "Allows greater goal dispersion than the Poisson assumption.",
        ),
        (
            "胜平负、比分、总进球和半全场概率。",
            "1X2, score, total-goals and half/full-time probabilities.",
        ),
        ("每日重估。", "Refitted daily."),
        ("至少 100 场已结算比赛。", "Requires at least 100 settled matches."),
        SHADOW_ROLE,
        "shadow",
    ),
}


MODEL_CODES = tuple(MODEL_CATALOG)


def public_metadata(code: str) -> dict[str, object]:
    metadata = MODEL_CATALOG[code]
    return {
        key: ({"zh-CN": value["zh_CN"], "en": value["en"]} if isinstance(value, dict) else value)
        for key, value in metadata.items()
    }
