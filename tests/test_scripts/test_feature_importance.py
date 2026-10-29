import re
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import numpy as np
import pytest

from scripts import feature_importance


@pytest.fixture(autouse=True)
def isolated_explanation_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("FQP_FEATURE_MODEL_ARTIFACT_PATH", str(tmp_path / "explanation.json"))


def test_confidence_condition_preserves_uncalibrated_group():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.description = []
    cursor.fetchall.return_value = []
    feature_importance.get_condition_performance(conn, dimension="confidence")
    query = cursor.execute.call_args.args[0]
    case = re.search(
        r"CASE\s+WHEN mp_home\.confidence_score.*?END AS confidence_range", query, re.S
    )
    assert case is not None
    with sqlite3.connect(":memory:") as db:
        for confidence, expected in (
            (None, "未校准/未知"),
            (0.0, "低信心 (<30%)"),
            (0.4, "中低信心 (30-50%)"),
            (0.6, "中高信心 (50-70%)"),
            (0.9, "高信心 (>70%)"),
        ):
            actual = db.execute(
                f"SELECT {case[0]} FROM (SELECT ? AS confidence_score) mp_home", (confidence,)
            ).fetchone()[0]
            assert actual == expected


class FakeClassifier:
    feature_importances_ = np.array([1.0])

    def fit(self, _features, _labels) -> None:
        return None

    def score(self, _features, _labels) -> float:
        return 1.0

    def predict_proba(self, _features) -> np.ndarray:
        return np.array([[0.2, 0.3, 0.5]])


class FakeCursor:
    query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, *_args) -> None:
        self.query = " ".join(query.split())

    def fetchone(self):
        return (88, "主队", "客队", *([1.0] * len(feature_importance.FEATURE_COLUMNS)))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class EvaluationCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._result_index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, *_args) -> None:
        self.queries.append(" ".join(query.split()))

    @property
    def description(self):
        if self._result_index == 0:
            return [
                ("model_name",),
                ("n",),
                ("avg_brier",),
                ("avg_logloss",),
                ("avg_rps",),
                ("avg_market_probability_move",),
                ("avg_closing_edge",),
                ("avg_odds_clv",),
                ("paired_market_samples",),
                ("brier_improvement_vs_market",),
                ("brier_improvement_ci_low",),
                ("brier_improvement_ci_high",),
            ]
        return [("total_evaluated",), ("overall_brier",), ("overall_logloss",)]

    def fetchall(self):
        self._result_index = 1
        return [("elo_rating", 12, 0.61, 1.01, 0.20, 0.02, 0.03, None, 12, 0.04, 0.01, 0.07)]

    def fetchone(self):
        return (12, 0.61, 1.01)


class EvaluationConnection:
    def __init__(self) -> None:
        self.cursor_instance = EvaluationCursor()

    def cursor(self) -> EvaluationCursor:
        return self.cursor_instance


class ComparisonCursor:
    def __init__(self) -> None:
        self.phase = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args) -> None:
        self.phase += 1

    @property
    def description(self):
        if self.phase == 1:
            return [
                ("model_name",),
                ("n_predictions",),
                ("avg_brier",),
                ("avg_log_loss",),
                ("avg_rps",),
                ("avg_market_probability_move",),
                ("avg_closing_edge",),
                ("avg_flb_score",),
            ]
        return [
            ("model_name",),
            ("hit_rate",),
            ("roi",),
            ("sharpe_ratio",),
            ("max_drawdown_pct",),
            ("profit_factor",),
            ("total_profit",),
        ]

    def fetchall(self):
        if self.phase == 1:
            return [("elo_rating", 2, 0.61, 1.01, 0.20, None, None, None)]
        return []


class ComparisonConnection:
    def __init__(self) -> None:
        self.cursor_instance = ComparisonCursor()

    def cursor(self) -> ComparisonCursor:
        return self.cursor_instance


class CaptureTrainingCursor:
    def __init__(self) -> None:
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        self.params = params
        self.query = " ".join(query.split())

    def fetchall(self):
        return []


class CaptureTrainingConnection:
    def __init__(self) -> None:
        self.cursor_instance = CaptureTrainingCursor()

    def cursor(self) -> CaptureTrainingCursor:
        return self.cursor_instance


def test_training_defers_shap_explainer_until_prediction_explanation(monkeypatch) -> None:
    classifier = FakeClassifier()
    classifier_factory = Mock(return_value=classifier)
    build_explainer = Mock()
    monkeypatch.setitem(
        sys.modules,
        "xgboost",
        SimpleNamespace(XGBClassifier=classifier_factory),
    )
    monkeypatch.setattr(
        feature_importance,
        "_load_training_data",
        lambda _conn: (
            np.ones((3, 1)),
            np.array([0, 1, 2]),
            [1, 2, 3],
            ["home_elo"],
        ),
    )
    monkeypatch.setattr(feature_importance, "_compute_permutation_importance", lambda *_args: {})
    monkeypatch.setattr(feature_importance, "_build_shap_explainer", build_explainer)

    monkeypatch.setattr(
        feature_importance.explanation_artifact,
        "make_artifact",
        lambda *_args: {"sha256": "fixture"},
    )
    publish = Mock()
    monkeypatch.setattr(feature_importance.explanation_artifact, "publish_artifact", publish)

    result = feature_importance.train_if_needed(object(), force=True)

    assert result["status"] == "ok"
    assert classifier_factory.call_args.kwargs["n_jobs"] == 1
    build_explainer.assert_not_called()
    publish.assert_called_once()


def test_permutation_importance_avoids_process_overhead_for_small_feature_sets(monkeypatch) -> None:
    import sklearn.inspection

    permutation = Mock(
        return_value=SimpleNamespace(
            importances_mean=np.array([0.2]),
            importances_std=np.array([0.01]),
        )
    )
    monkeypatch.setattr(sklearn.inspection, "permutation_importance", permutation)

    feature_importance._compute_permutation_importance(
        FakeClassifier(),
        np.ones((3, 1)),
        np.array([0, 1, 2]),
        ["home_elo"],
    )

    assert permutation.call_args.kwargs["n_jobs"] == 1


def _mock_explanation_artifact(monkeypatch):
    state = {
        "artifact": {
            "features": [feature_importance.FEATURE_COLUMNS[0]],
            "sha256": "fixture",
            "info": {"trained_at": "2026-10-29T00:00:00+00:00"},
        },
        "error": None,
    }
    monkeypatch.setattr(feature_importance.explanation_artifact, "read_state", lambda: state)
    monkeypatch.setattr(
        feature_importance.explanation_artifact,
        "load_classifier",
        lambda _artifact: FakeClassifier(),
    )


def test_prediction_stays_available_when_optional_shap_setup_fails(monkeypatch) -> None:
    _mock_explanation_artifact(monkeypatch)
    monkeypatch.setattr(
        feature_importance,
        "_build_shap_explainer",
        Mock(side_effect=RuntimeError("SHAP unavailable")),
    )

    result = feature_importance.explain_prediction(FakeConnection(), match_id=88)

    assert result["status"] == "ok"
    assert result["shap_values"] == []
    assert result["base_values"] == []
    assert result["predicted_probs"] == {"home": 0.5, "draw": 0.3, "away": 0.2}


def test_prediction_explanation_uses_latest_prematch_feature_snapshot(monkeypatch) -> None:
    _mock_explanation_artifact(monkeypatch)
    monkeypatch.setattr(feature_importance, "_build_shap_explainer", lambda _model: None)
    conn = FakeConnection()

    feature_importance.explain_prediction(conn, match_id=88)

    assert "fs.snapshot_time < m.kickoff_time" in conn.cursor_instance.query


def test_evaluation_summary_assigns_metrics_directly_to_their_model_version() -> None:
    conn = EvaluationConnection()

    result = feature_importance.get_evaluation_summary(conn)

    assert result["models"][0]["n"] == 12
    summary_query = conn.cursor_instance.queries[0]
    assert "DISTINCT ON (source_mem.match_id, source_mv.model_name)" in summary_query
    assert "source_mv.model_name AS canonical_model_name" in summary_query
    assert "COUNT(DISTINCT mem.match_id) AS n" in summary_query
    assert "market_baseline_scores" in summary_query
    assert "baseline.brier_score AS market_brier_score" in summary_query
    assert "JOIN model_predictions" not in summary_query
    assert "source_mem.snapshot_time < source_match.kickoff_time" in summary_query
    assert "source_mem.play_type = 'spf'" in summary_query
    assert "source_result.result_status IN ('final', 'confirmed')" in summary_query
    assert result["models"][0]["avg_market_probability_move"] == 0.02
    assert result["models"][0]["avg_closing_edge"] == 0.03
    assert result["models"][0]["avg_odds_clv"] is None
    assert result["models"][0]["brier_improvement_vs_market"] == 0.04
    assert result["models"][0]["brier_improvement_ci_low"] == 0.01
    assert result["models"][0]["brier_improvement_ci_high"] == 0.07
    assert result["models"][0]["sample_status"] == "monitoring"
    assert result["models"][0]["is_publishable"] is False
    assert result["overall"]["publication_min_samples"] == 100
    assert result["overall"]["publishable_models"] == 0


def test_latest_prediction_scope_excludes_post_match_predictions() -> None:
    query = " ".join(feature_importance._LATEST_PREDICTIONS_CTE.split())

    assert "source_mp.predict_time < source_match.kickoff_time" in query
    assert "source_mp.validation_status = 'valid'" in query
    assert "model_independent" in query
    assert "source_result.result_status IN ('final', 'confirmed')" in query
    assert "DISTINCT ON ( source_mp.match_id, source_mv.model_name" in query
    assert "source_mv.model_name AS canonical_model_name" in query


def test_model_comparison_preserves_unavailable_metrics_as_null() -> None:
    result = feature_importance.get_model_comparison_data(ComparisonConnection())

    assert result["models"][0]["market_probability_move"] is None
    assert result["models"][0]["closing_edge"] is None
    assert result["models"][0]["odds_clv"] is None
    assert result["models"][0]["flb_score"] is None


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf")])
def test_model_comparison_keeps_missing_losses_and_backtest_values_unknown(missing):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    metric_names = [
        "model_name",
        "n_predictions",
        "avg_brier",
        "avg_log_loss",
        "avg_rps",
        "avg_market_probability_move",
        "avg_closing_edge",
        "avg_flb_score",
    ]
    backtest_names = [
        "model_name",
        "hit_rate",
        "roi",
        "sharpe_ratio",
        "max_drawdown_pct",
        "profit_factor",
        "total_profit",
    ]
    cursor.description = [(name,) for name in metric_names]

    def fetch():
        if cursor.execute.call_count == 1:
            cursor.description = [(name,) for name in backtest_names]
            return [
                ("unknown", 2, 0.6, missing, missing, missing, missing, missing),
                ("zero", 2, 0, 0, 0, 0, 0, 0),
            ]
        return [
            ("unknown", missing, missing, missing, missing, missing, missing),
            ("zero", 0, 0, 0, 0, 0, 0),
        ]

    # get_model_comparison_data reads description before fetchall.
    cursor.fetchall.side_effect = fetch
    result = feature_importance.get_model_comparison_data(conn)
    by_name = {m["name"]: m for m in result["models"]}
    for key in ("log_loss", "rps", "roi", "sharpe", "profit_factor", "total_profit"):
        assert by_name["unknown"][key] is None
        assert by_name["zero"][key] == 0
    assert result["models"][0]["name"] == "zero"


def test_feature_training_uses_one_pre_match_snapshot_per_match() -> None:
    conn = CaptureTrainingConnection()

    result = feature_importance._load_training_data(conn, min_samples=1)

    assert result is None
    query = conn.cursor_instance.query
    assert "DISTINCT ON (fs.match_id)" in query
    assert "fs.snapshot_time < m.kickoff_time" in query


@pytest.mark.parametrize(
    "labels", [[0] * 100, [1] * 100, [2] * 100, [0, 1] * 50, [0, 2] * 50, [1, 2] * 50]
)
def test_explanation_missing_outcome_classes_returns_friendly_error_without_replacing_cache(
    monkeypatch, labels
):
    factory = Mock(return_value=FakeClassifier())
    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=factory))
    publish = Mock()
    monkeypatch.setattr(feature_importance.explanation_artifact, "publish_artifact", publish)
    monkeypatch.setattr(
        feature_importance,
        "_load_training_data",
        lambda _conn: (np.ones((100, 1)), np.array(labels), list(range(100)), ["home_elo"]),
    )
    result = feature_importance.train_if_needed(object(), force=True)
    assert result["status"] == "error"
    assert "类别" in result["error"]
    factory.assert_not_called()
    publish.assert_not_called()


def test_explanation_all_missing_features_returns_friendly_error(monkeypatch):
    factory = Mock(return_value=FakeClassifier())
    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=factory))
    monkeypatch.setattr(
        feature_importance,
        "_load_training_data",
        lambda _conn: (np.empty((102, 0)), np.tile([0, 1, 2], 34), list(range(102)), []),
    )
    result = feature_importance.train_if_needed(object(), force=True)
    assert result["status"] == "error"
    assert "特征" in result["error"]
    factory.assert_not_called()
