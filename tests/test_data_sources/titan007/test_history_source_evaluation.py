"""Retrospective holdouts cannot train on their labels or borrow future coverage."""

import hashlib
import json
import math
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from scripts.backtest_engine import ResearchEvaluationConfig
from scripts.evaluation_metrics import compute_match_metrics
from scripts.football_history_source_evaluation import evaluate_source_score_research
from scripts.football_history_source_research import OFFICIAL_FIELDS
from scripts.model_artifact_identity import canonical_json_bytes
from tests.test_data_sources.titan007.test_history_research import history, match

MODULE = "scripts.football_history_source_evaluation"
TZ = ZoneInfo("Asia/Shanghai")


def diagnose(h=None, rows=None):
    from scripts.football_history_source_evaluation import diagnose_source_score_training

    h, rows = inputs() if h is None else (h, rows)
    return diagnose_source_score_training(h, rows, development_cutoff="2026-09-09T00:00:00+08:00")


def test_training_diagnosis_is_bounded_paired_and_does_not_rescore_later_labels():
    result = diagnose()
    assert result["diagnosis_status"] == "selected_for_research"
    assert result["development_manifest"]["summary"]["included_count"] == 38
    assert result["later_labels_not_evaluated"] == 7
    assert [c["extra_team_ridge"] for c in result["candidates"]] == [0, 1, 5]
    paired_ids = None
    for candidate in result["candidates"]:
        assert len(candidate["development_windows"]) == 2
        assert candidate["fully_paired"] is True
        current = []
        for w in candidate["development_windows"]:
            assert w["final_holdout"] is False
            current.extend(p["source_match_id"] for p in w["predictions"])
            assert all(p["source_match_id"] <= 38 for p in w["predictions"])
        assert len(current) == 14
        assert paired_ids is None or paired_ids == current
        paired_ids = current
    assert result["selected_refit"]["n_matches"] == 38
    assert result["calibration"]["status"] == "insufficient_samples"
    assert result["calibration"]["available_out_of_fold_samples"] == 14
    assert result["calibration"]["minimum_training_samples"] == 100
    assert result["calibration"]["minimum_validation_samples"] == 25
    assert result["uncertainty"]["confidence_intervals"] == "not_estimated"
    assert result["usage"]["production_ready"] is False
    assert result["production_model_writes"] == 0


def test_later_scores_do_not_change_training_selection_fits_or_predictions():
    first = diagnose()
    changed = diagnose(
        *inputs(changes={i: {"home_goals": 9, "away_goals": 0} for i in range(39, 46)})
    )
    for a, b in zip(first["candidates"], changed["candidates"], strict=True):
        assert a["aggregate_metrics"] == b["aggregate_metrics"]
        for w1, w2 in zip(a["development_windows"], b["development_windows"], strict=True):
            assert w1["fit"] == w2["fit"]
            assert w1["predictions"] == w2["predictions"]
    assert first["selected_extra_team_ridge"] == changed["selected_extra_team_ridge"]
    assert first["selected_refit"] == changed["selected_refit"]


@pytest.mark.parametrize("cutoff", ["2026-09-09", "2026-09-09T01:00:00+08:00"])
def test_training_diagnosis_requires_explicit_beijing_midnight(cutoff):
    from scripts.football_history_source_evaluation import diagnose_source_score_training

    with pytest.raises(ValueError):
        diagnose_source_score_training(*inputs(), development_cutoff=cutoff)


def test_any_failed_candidate_blocks_selection_instead_of_cherry_picking_coverage():
    from scripts.football_history_source_research import _fit_source_labels

    def fit(manifest, **kwargs):
        if kwargs.get("extra_team_ridge") == 1:
            return {"converged": False}
        return _fit_source_labels(manifest, **kwargs)

    with patch(MODULE + "._fit_source_labels", side_effect=fit):
        result = diagnose()
    assert result["diagnosis_status"] == "incomplete"
    assert result["selected_extra_team_ridge"] is None
    assert result["selected_refit"] is None
    assert result["calibration"]["status"] == "selection_unavailable"


def test_equal_candidate_losses_prefer_smaller_ridge_and_report_refit_failure():
    from scripts.football_history_source_research import _fit_source_labels

    def identical(manifest, **kwargs):
        if len(manifest["included"]) == 38:
            return {"converged": False}
        return _fit_source_labels(manifest)

    with patch(MODULE + "._fit_source_labels", side_effect=identical):
        result = diagnose()
    assert result["selected_extra_team_ridge"] == 0
    assert result["diagnosis_status"] == "refit_failed"


def test_training_diagnosis_cli_keeps_default_mode_and_refuses_overwrite(tmp_path):
    h, rows = inputs()
    receipt, output = tmp_path / "input.json", tmp_path / "diagnosis.json"
    receipt.write_text(json.dumps({"history": h, "official_rows": rows}, default=str))
    command = [
        sys.executable,
        "-m",
        MODULE,
        "--input",
        str(receipt),
        "--output",
        str(output),
        "--development-cutoff",
        "2026-09-09T00:00:00+08:00",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text())
    assert result["version"] == "fqp.history-source-training-diagnosis/v1"
    assert result["input_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert subprocess.run(command, capture_output=True, timeout=30).returncode != 0

    # A team seen only in the development validation segment cannot borrow
    # later coverage. All candidates then have incomplete paired coverage.
    h, rows = inputs(
        changes={i: {"home_team_id": 30, "source_home_team_id": 300} for i in range(34, 39)}
    )
    receipt.write_text(json.dumps({"history": h, "official_rows": rows}, default=str))
    command[command.index("--output") + 1] = str(tmp_path / "incomplete.json")
    assert subprocess.run(command, capture_output=True, timeout=30).returncode == 2
    incomplete = json.loads((tmp_path / "incomplete.json").read_text())
    assert incomplete["diagnosis_status"] == "incomplete"
    assert incomplete["selected_extra_team_ridge"] is None


def test_training_diagnosis_strict_cutoff_and_utc_equivalent_are_stable():
    from scripts.football_history_source_evaluation import diagnose_source_score_training

    h, rows = inputs(changes={38: {"kickoff_at": "2026-09-09T00:00:00+08:00"}})
    result = diagnose(h, rows)
    assert result["development_manifest"]["summary"]["included_count"] == 37
    assert result["later_labels_not_evaluated"] == 8
    assert result == diagnose_source_score_training(
        h, list(reversed(rows)), development_cutoff="2026-09-08T16:00:00+00:00"
    )
    assert (
        result["sha256"]
        == hashlib.sha256(
            canonical_json_bytes({k: v for k, v in result.items() if k != "sha256"})
        ).hexdigest()
    )


def test_training_diagnosis_does_not_fit_calibration_below_existing_threshold():
    with patch("scripts.probability_calibration.fit_temperature_scaling") as fit_calibration:
        result = diagnose()
    fit_calibration.assert_not_called()
    assert result["calibration"]["profile"] is None


def test_training_diagnosis_scores_are_recomputed_on_the_same_development_rows():
    result = diagnose()
    for candidate in result["candidates"]:
        losses = []
        for window in candidate["development_windows"]:
            for row in window["predictions"]:
                expected = compute_match_metrics(
                    row["model_probabilities"], {}, row["actual_result"]
                )
                assert row["metrics"]["model"] == {
                    k: expected[k] for k in ("brier_score", "log_loss", "rps")
                }
                losses.append(expected["log_loss"])
        assert candidate["aggregate_metrics"]["model"]["log_loss"] == pytest.approx(
            sum(losses) / len(losses), abs=1e-8
        )


def inputs(count=45, changes=None):
    rows = [
        match(
            i,
            **{
                "official_match_id": None,
                "home_goals": i % 3,
                "away_goals": (i + 1) % 3,
                **(changes or {}).get(i, {}),
            },
        )
        for i in range(1, count + 1)
    ]
    evidence = [
        {**dict.fromkeys(OFFICIAL_FIELDS), "source_match_id": i} for i in range(1, count + 1)
    ]
    return history(rows), evidence


def evaluate(**kwargs):
    return evaluate_source_score_research(*inputs(), **kwargs)


def test_real_fits_have_disjoint_chronological_training_and_paired_baselines():
    result = evaluate()
    assert result["evaluation_status"] == "evaluated"
    windows = [*result["folds"], result["final_holdout"]]
    assert len(windows) == 3
    tested = set()
    for window in windows:
        trained = {r["source_match_id"] for r in window["training_manifest"]["included"]}
        current = {r["source_match_id"] for r in window["predictions"]}
        assert not current & (trained | tested)
        tested |= current
        assert window["fit"]["converged"] is True
        assert window["fit"]["n_matches"] == len(trained)
        assert window["sample_count"] == 7
        cutoff = datetime.fromisoformat(window["train_cutoff"])
        assert all(
            datetime.fromisoformat(r["kickoff_at"]) < cutoff
            for r in window["training_manifest"]["included"]
        )
        assert cutoff + timedelta(hours=24) == datetime.fromisoformat(
            window["test_start"] + "T00:00:00+08:00"
        )
        for name in ("model", "uniform", "training_frequency"):
            assert window["metrics"][name]["sample_count"] == len(current)
        for row in window["predictions"]:
            assert row["label_id"].startswith("titan007:match:")
            assert row["evidence_status"] == "source_only"
            assert row["source_published_at"] is None
            assert sum(row["model_probabilities"].values()) == pytest.approx(1)
    assert result["final_holdout"]["final_holdout"] is True
    assert result["usage"]["point_in_time_replay_verified"] is False
    assert result["usage"]["production_ready"] is False
    assert result["market_comparison"]["status"] == "not_evaluated"
    assert result["claims_model_beats_market"] is False


def test_future_holdout_scores_never_change_any_fit_or_baseline():
    first = evaluate()
    # Last seven days are the reserved final block; keep fixtures identical.
    changed = evaluate_source_score_research(
        *inputs(changes={i: {"home_goals": 8, "away_goals": 0} for i in range(39, 46)})
    )
    for before, after in zip(
        [*first["folds"], first["final_holdout"]],
        [*changed["folds"], changed["final_holdout"]],
        strict=True,
    ):
        assert before["fit"] == after["fit"]
        assert before["baseline_probabilities"] == after["baseline_probabilities"]
        assert [p["model_probabilities"] for p in before["predictions"]] == [
            p["model_probabilities"] for p in after["predictions"]
        ]
    assert first["final_holdout"]["metrics"] != changed["final_holdout"]["metrics"]


def test_cutoff_equality_and_same_business_day_are_not_training():
    original = evaluate()
    cutoff = datetime.fromisoformat(original["folds"][0]["train_cutoff"])
    start = cutoff + timedelta(hours=24)
    h, rows = inputs(
        changes={1: {"kickoff_at": cutoff}, 2: {"kickoff_at": start + timedelta(hours=1)}}
    )
    result = evaluate_source_score_research(h, rows)
    fold = result["folds"][0]
    assert not {1, 2} & {r["source_match_id"] for r in fold["training_manifest"]["included"]}
    assert {"source_match_id": 1, "reason": "kickoff_embargo"} in fold["training_manifest"][
        "excluded"
    ]
    assert 2 in {r["source_match_id"] for r in fold["predictions"]}


def test_beijing_date_includes_utc_previous_evening_in_next_day():
    h, rows = inputs(changes={45: {"kickoff_at": "2026-09-15T17:30:00+00:00"}})
    result = evaluate_source_score_research(h, rows)
    assert result["final_holdout"]["test_end"] == "2026-09-16"
    assert result["final_holdout"]["predictions"][-1]["business_date"] == "2026-09-16"


def test_scores_and_training_only_laplace_baseline_match_existing_metrics():
    result = evaluate()
    window = result["final_holdout"]
    samples = window["training_manifest"]["included"]
    expected = {k: 1 for k in ("3", "1", "0")}
    for s in samples:
        expected[
            "3"
            if s["home_goals"] > s["away_goals"]
            else "1"
            if s["home_goals"] == s["away_goals"]
            else "0"
        ] += 1
    assert window["baseline_probabilities"]["training_frequency"] == {
        k: n / (len(samples) + 3) for k, n in expected.items()
    }
    row = window["predictions"][0]
    expected_metrics = compute_match_metrics(row["model_probabilities"], {}, row["actual_result"])
    assert row["metrics"]["model"] == {
        k: expected_metrics[k] for k in ("brier_score", "log_loss", "rps")
    }
    assert window["comparison"]["uniform"]["log_loss_delta_model_minus_baseline"] == pytest.approx(
        window["metrics"]["model"]["log_loss"] - math.log(3), abs=1e-6
    )


def test_unseen_teams_are_excluded_without_future_counts_or_full_cohort_fit():
    h, rows = inputs(changes={45: {"home_team_id": 30, "source_home_team_id": 300}})
    result = evaluate_source_score_research(h, rows)
    window = result["final_holdout"]
    assert {"source_match_id": 45, "reason": "team_unseen_in_training"} in window["excluded"]
    assert window["candidate_count"] == 7
    assert window["sample_count"] == 6
    assert window["metrics"]["uniform"]["sample_count"] == 6
    assert 30 not in window["fit"]["attack"]


def test_training_sparse_counts_are_pruned_iteratively_not_from_full_cohort():
    changes = {i: {"home_team_id": 30, "source_home_team_id": 300} for i in range(1, 5)}
    result = evaluate_source_score_research(*inputs(changes=changes))
    window = result["folds"][0]
    assert window["training_manifest"]["summary"]["team_match_counts"].keys() == {"10", "20"}
    assert all(
        s["source_match_id"] not in range(1, 5) for s in window["training_manifest"]["included"]
    )
    assert (
        sum(
            e["reason"] == "team_below_training_minimum"
            for e in window["training_manifest"]["excluded"]
        )
        == 4
    )


def test_training_pruning_cascades_when_removing_an_undercovered_opponent():
    # Team 30 initially has five matches, but one is against team 40 (only one).
    changes = {i: {"home_team_id": 30, "source_home_team_id": 300} for i in range(1, 6)}
    changes[1].update({"away_team_id": 40, "source_away_team_id": 400})
    result = evaluate_source_score_research(*inputs(changes=changes))
    training = result["folds"][0]["training_manifest"]
    assert set(training["summary"]["team_match_counts"]) == {"10", "20"}
    assert {r["source_match_id"] for r in training["excluded"]} >= set(range(1, 6))


def test_empty_calendar_windows_are_incomplete_not_a_pass():
    config = ResearchEvaluationConfig(fold_count=2, test_window_days=1, holdout_days=1)
    # Move the last fixture far ahead; the two preceding calendar days are empty.
    result = evaluate_source_score_research(
        *inputs(changes={45: {"kickoff_at": "2026-10-20T00:00:00+08:00"}}), config=config
    )
    assert result["evaluation_status"] == "incomplete"
    assert result["folds"][0]["candidate_count"] == 0
    assert result["folds"][0]["metrics"]["model"]["sample_count"] == 0
    assert result["folds"][0]["coverage"] is None


def test_report_size_limit_is_enforced_without_exporting_an_oversized_success():
    with pytest.raises(ValueError, match="report exceeds"):
        evaluate(
            config=ResearchEvaluationConfig(
                fold_count=2, test_window_days=7, holdout_days=7, max_report_bytes=1024
            )
        )


@pytest.mark.parametrize(
    "fit",
    [
        {"error": "Insufficient data", "converged": False},
        {"converged": False, "optimizer_message": "limit"},
    ],
)
def test_unavailable_fit_never_scores_a_baseline_on_unpaired_samples(fit):
    with patch(MODULE + "._fit_source_labels", return_value=fit):
        result = evaluate()
    assert result["evaluation_status"] == "incomplete"
    for window in [*result["folds"], result["final_holdout"]]:
        assert window["sample_count"] == 0
        assert window["metrics"]["uniform"]["log_loss"] is None
        assert window["excluded_by_reason"] == {"model_fit_unavailable": 7}


def test_invalid_rates_do_not_become_zero_probability_predictions():
    with patch(MODULE + "._research_prediction_probabilities", return_value=None):
        result = evaluate()
    assert result["evaluation_status"] == "incomplete"
    assert result["final_holdout"]["excluded_by_reason"] == {"model_rate_unavailable": 7}


@pytest.mark.parametrize(
    "config",
    [
        ResearchEvaluationConfig(min_team_matches=4),
        ResearchEvaluationConfig(fold_count=True),
        ResearchEvaluationConfig(test_window_days=1.5),
        ResearchEvaluationConfig(max_matches=10),
    ],
)
def test_invalid_or_over_budget_config_is_rejected(config):
    with pytest.raises((TypeError, ValueError)):
        evaluate(config=config)


def test_insufficient_calendar_history_fails_before_fit():
    with patch(MODULE + "._fit_source_labels") as fitter:
        with pytest.raises(ValueError, match="history"):
            evaluate_source_score_research(*inputs(count=12))
    fitter.assert_not_called()


def test_hash_order_and_input_provenance_are_deterministic_and_tampering_fails():
    h, rows = inputs()
    a = evaluate_source_score_research(h, rows, input_receipt_sha256="a" * 64)
    b = evaluate_source_score_research(h, rows[::-1], input_receipt_sha256="a" * 64)
    assert a == b
    for value in (a, *[w["training_manifest"] for w in [*a["folds"], a["final_holdout"]]]):
        from scripts.model_artifact_identity import canonical_json_bytes

        assert (
            value["sha256"]
            == hashlib.sha256(
                canonical_json_bytes({k: v for k, v in value.items() if k != "sha256"})
            ).hexdigest()
        )
    bad = deepcopy(h)
    bad["included"][0]["home_goals"] += 1
    with pytest.raises(ValueError):
        evaluate_source_score_research(bad, rows)


def test_cli_uses_saved_local_receipt_and_refuses_overwrite(tmp_path):
    h, rows = inputs()
    receipt, output = tmp_path / "receipt.json", tmp_path / "evaluation.json"
    receipt.write_text(json.dumps({"history": h, "official_rows": rows}, default=str))
    cmd = [sys.executable, "-m", MODULE, "--input", str(receipt), "--output", str(output)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text())
    assert result["input_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert result["summary"]["scored_count"] == 21
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode != 0
    assert json.loads(output.read_text()) == result


def test_cli_incomplete_fit_returns_diagnostic_exit_two(tmp_path):
    h, rows = inputs(count=25)
    receipt, output = tmp_path / "small.json", tmp_path / "evaluation.json"
    receipt.write_text(json.dumps({"history": h, "official_rows": rows}, default=str))
    completed = subprocess.run(
        [sys.executable, "-m", MODULE, "--input", str(receipt), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2, completed.stderr
    assert json.loads(output.read_text())["evaluation_status"] == "incomplete"
