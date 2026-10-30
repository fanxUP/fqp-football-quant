"""A frozen source-score candidate can only forecast genuinely later fixtures."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from scripts.evaluation_metrics import compute_match_metrics
from scripts.football_history_source_evaluation import diagnose_source_score_training
from scripts.football_history_source_research import _hashed
from scripts.model_artifact_identity import canonical_json_bytes
from tests.test_data_sources.titan007.test_history_source_evaluation import inputs

MODULE = "scripts.football_history_prospective"
NOW = datetime(2026, 10, 30, 4, tzinfo=UTC)


@pytest.fixture(scope="module")
def diagnosis_inputs():
    h, rows = inputs()
    receipt = {"history": h, "official_rows": rows, "checked_at": "2026-10-30T00:00:00Z"}
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    diagnosis = diagnose_source_score_training(
        h, rows, development_cutoff="2026-09-09T00:00:00+08:00", input_receipt_sha256=digest
    )
    return diagnosis, receipt, digest


def freeze(data, **kwargs):
    from scripts.football_history_prospective import freeze_candidate

    diagnosis, receipt, digest = data
    return freeze_candidate(
        diagnosis,
        receipt,
        expected_sha256=diagnosis["sha256"],
        receipt_sha256=digest,
        now=NOW,
        **kwargs,
    )


def fixture(mid=100, **changes):
    return {
        "source_match_id": mid,
        "home_team_id": 10,
        "away_team_id": 20,
        "kickoff_at": (NOW + timedelta(days=1, minutes=mid - 100)).isoformat(),
        "status": "scheduled",
        "home_goals": None,
        "away_goals": None,
        **changes,
    }


def fixtures(rows=None, **changes):
    return {
        "version": "fqp.history-source-fixtures/v1",
        "source_name": "titan007",
        "source_competition_id": 36,
        "study_season": "2026-2027",
        "captured_at": NOW.isoformat(),
        "batch": {
            "id": 2,
            "state": "published",
            "content_sha256": "b" * 64,
            "imported_at": "2026-10-29T00:00:00Z",
        },
        "fixtures": [fixture()] if rows is None else rows,
        **changes,
    }


def predict(candidate, receipt=None, now=NOW):
    from scripts.football_history_prospective import predict_fixtures

    return predict_fixtures(
        candidate,
        fixtures() if receipt is None else receipt,
        expected_sha256=candidate["sha256"],
        now=now,
    )


def score(prediction, receipt, now=NOW + timedelta(days=2)):
    from scripts.football_history_prospective import score_forecast

    return score_forecast(prediction, receipt, expected_sha256=prediction["sha256"], now=now)


def results(rows=None):
    return fixtures(
        [fixture(status="finished", home_goals=0, away_goals=2)] if rows is None else rows,
        captured_at=(NOW + timedelta(days=2)).isoformat(),
        score_scope="source_reported_full_match",
    )


def test_freeze_retains_exact_selected_fit_and_does_not_train(diagnosis_inputs):
    with patch("scripts.football_history_source_research._fit_source_labels") as fit:
        frozen = freeze(diagnosis_inputs)
    fit.assert_not_called()
    assert frozen["fit"] == diagnosis_inputs[0]["selected_refit"]
    assert frozen["training_manifest"] == diagnosis_inputs[0]["development_manifest"]
    assert frozen["frozen_at"] == NOW.isoformat()
    assert frozen["observation_end"] == (NOW + timedelta(days=14)).isoformat()
    assert frozen["input_observed_at"] == "2026-10-30T00:00:00+00:00"
    assert frozen["usage"]["production_ready"] is False
    assert frozen["usage"]["spf_regulation_score_verified"] is False


@pytest.mark.parametrize("kind", ["hash", "receipt", "manifest", "fit", "not_selected", "clock"])
def test_freeze_rejects_tampering_wrong_inputs_or_backdated_clock(diagnosis_inputs, kind):
    d, receipt, digest = deepcopy(diagnosis_inputs)
    from scripts.football_history_prospective import freeze_candidate

    expected, now = d["sha256"], NOW
    if kind == "hash":
        d["selected_refit"]["home_advantage"] += 1
    elif kind == "receipt":
        digest = "c" * 64
    elif kind == "manifest":
        d["development_manifest"]["included"][0]["home_goals"] += 1
        d = _hashed({k: v for k, v in d.items() if k != "sha256"})
        expected = d["sha256"]
    elif kind == "fit":
        d["selected_refit"]["n_matches"] += 1
        d["selected_refit_sha256"] = hashlib.sha256(
            canonical_json_bytes(d["selected_refit"])
        ).hexdigest()
        d = _hashed({k: v for k, v in d.items() if k != "sha256"})
        expected = d["sha256"]
    elif kind == "not_selected":
        d["diagnosis_status"] = "incomplete"
        d = _hashed({k: v for k, v in d.items() if k != "sha256"})
        expected = d["sha256"]
    else:
        now = NOW - timedelta(days=1)
    with pytest.raises(ValueError):
        freeze_candidate(d, receipt, expected_sha256=expected, receipt_sha256=digest, now=now)


def test_prediction_reuses_frozen_parameters_and_existing_run_manifest(diagnosis_inputs):
    frozen = freeze(diagnosis_inputs)
    with patch("scripts.football_history_source_research._fit_source_labels") as fit:
        output = predict(frozen)
    fit.assert_not_called()
    row = output["predictions"][0]
    assert output["forecast_status"] == "recorded"
    assert sum(row["model_probabilities"].values()) == pytest.approx(1)
    assert row["predicted_at"] == NOW.isoformat()
    assert output["candidate_sha256"] == frozen["sha256"]
    assert output["run_manifest"]["schema_version"] == "fqp.model-prediction-run/v1"
    assert (
        output["run_manifest"]["model_manifest"][0]["model_name"] == "history_source_maher_research"
    )
    assert "model_version_id" not in output["run_manifest"]["model_manifest"][0]
    assert output["summary"] == {"supplied": 1, "predicted": 1, "excluded": 0}
    assert "actual_result" not in row


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"kickoff_at": NOW.isoformat()}, "already_started"),
        ({"kickoff_at": (NOW + timedelta(days=14)).isoformat()}, "outside_observation_window"),
        ({"status": "finished", "home_goals": 2, "away_goals": 0}, "not_scheduled_or_has_score"),
        ({"source_match_id": 1}, "seen_in_training"),
        ({"home_team_id": 30}, "team_unseen_in_training"),
        ({"kickoff_at": None}, "invalid_fixture_identity"),
        ({"home_team_id": True}, "invalid_fixture_identity"),
    ],
)
def test_forecast_exclusions_are_explicit_and_not_success(diagnosis_inputs, changes, reason):
    output = predict(freeze(diagnosis_inputs), fixtures([fixture(**changes)]))
    assert output["forecast_status"] == "no_eligible_fixtures"
    assert output["summary"]["predicted"] == 0
    assert output["excluded"][0]["reason"] == reason


def test_forecast_keeps_all_eligible_rows_sorted_and_reports_coverage(diagnosis_inputs):
    frozen = freeze(diagnosis_inputs)
    receipt = fixtures([fixture(102), fixture(101), fixture(103, home_team_id=30)])
    first = predict(frozen, receipt)
    receipt["fixtures"].reverse()
    second = predict(frozen, receipt)
    assert first == second
    assert [r["source_match_id"] for r in first["predictions"]] == [101, 102]
    assert first["summary"] == {"supplied": 3, "predicted": 2, "excluded": 1}


@pytest.mark.parametrize(
    "changes",
    [
        {"source_competition_id": 37},
        {"study_season": "2025-2026"},
        {"captured_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"batch": {"id": 2, "state": "building"}},
    ],
)
def test_wrong_or_future_fixture_snapshot_is_rejected(diagnosis_inputs, changes):
    with pytest.raises(ValueError):
        predict(freeze(diagnosis_inputs), fixtures(**changes))


@pytest.mark.parametrize(
    "rows",
    [
        [fixture(), fixture()],
        [
            fixture(),
            fixture(101, home_team_id=20, away_team_id=10, kickoff_at=fixture()["kickoff_at"]),
        ],
    ],
)
def test_duplicate_source_ids_or_events_are_rejected(diagnosis_inputs, rows):
    with pytest.raises(ValueError, match="Duplicate"):
        predict(freeze(diagnosis_inputs), fixtures(rows))


def test_changed_candidate_or_runtime_cannot_silently_generate_predictions(diagnosis_inputs):
    frozen = freeze(diagnosis_inputs)
    bad = deepcopy(frozen)
    bad["fit"]["home_advantage"] += 0.1
    with pytest.raises(ValueError):
        predict(bad)
    with patch(MODULE + ".fingerprint_runtime_sources", return_value={"files": {}}):
        with pytest.raises(ValueError):
            predict(frozen)


def test_scoring_keeps_missing_results_pending_and_excludes_reschedules(diagnosis_inputs):
    prediction = predict(
        freeze(diagnosis_inputs), fixtures([fixture(100), fixture(101), fixture(102)])
    )
    receipt = results(
        [
            fixture(100, status="finished", home_goals=0, away_goals=2),
            fixture(
                102,
                status="finished",
                home_goals=1,
                away_goals=1,
                kickoff_at=(NOW + timedelta(days=3)).isoformat(),
            ),
        ]
    )
    output = score(prediction, receipt)
    assert output["evaluation_status"] == "partially_scored"
    assert output["summary"] == {"predicted": 3, "scored": 1, "pending": 1, "excluded": 1}
    assert output["pending"] == [{"source_match_id": 101, "reason": "result_missing"}]
    assert output["excluded"] == [{"source_match_id": 102, "reason": "fixture_identity_changed"}]
    expected = compute_match_metrics(prediction["predictions"][0]["model_probabilities"], {}, "0")
    assert output["metrics"]["model"]["log_loss"] == pytest.approx(expected["log_loss"], abs=1e-8)
    assert all(m["sample_count"] == 1 for m in output["metrics"].values())
    assert output["promotion_allowed"] is False


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"score_scope": "regulation_90"}, "score_scope_unverified"),
        (
            {"fixtures": [fixture(status="finished", home_goals=True, away_goals=2)]},
            "invalid_score",
        ),
        ({"fixtures": [fixture(status="finished", home_goals=-1, away_goals=2)]}, "invalid_score"),
    ],
)
def test_score_semantics_and_scores_are_not_silently_converted(diagnosis_inputs, changes, reason):
    prediction = predict(freeze(diagnosis_inputs))
    receipt = results()
    receipt.update(changes)
    output = score(prediction, receipt)
    assert output["summary"]["scored"] == 0
    assert output["excluded"][0]["reason"] == reason
    assert output["metrics"]["model"]["log_loss"] is None


def test_pending_is_not_a_scored_zero_and_pre_result_capture_is_rejected(diagnosis_inputs):
    prediction = predict(freeze(diagnosis_inputs))
    output = score(prediction, results([]))
    assert output["evaluation_status"] == "awaiting_results"
    assert output["metrics"]["uniform"]["sample_count"] == 0
    with pytest.raises(ValueError):
        score(prediction, results(), now=NOW)


def test_fixture_starting_during_calculation_cannot_be_recorded_as_prekickoff(diagnosis_inputs):
    frozen = freeze(diagnosis_inputs)
    with patch(MODULE + "._clock", side_effect=[NOW, NOW + timedelta(days=1)]):
        output = predict(frozen)
    assert output["forecast_status"] == "no_eligible_fixtures"
    assert output["excluded"] == [{"source_match_id": 100, "reason": "started_during_computation"}]


def test_score_requires_result_observation_after_kickoff(diagnosis_inputs):
    prediction = predict(freeze(diagnosis_inputs))
    receipt = results()
    receipt["captured_at"] = (NOW + timedelta(hours=1)).isoformat()
    output = score(prediction, receipt)
    assert output["excluded"] == [
        {"source_match_id": 100, "reason": "result_observed_before_kickoff"}
    ]


def test_complete_paired_score_does_not_refit_or_modify_prediction(diagnosis_inputs):
    prediction = predict(freeze(diagnosis_inputs))
    original = deepcopy(prediction)
    with patch("scripts.football_history_source_research._fit_source_labels") as fit:
        output = score(prediction, results())
    fit.assert_not_called()
    assert prediction == original
    assert output["evaluation_status"] == "evaluated"
    assert output["summary"] == {"predicted": 1, "scored": 1, "pending": 0, "excluded": 0}
    assert output["promotion_allowed"] is False


def test_cli_freezes_with_actual_clock_and_refuses_overwrite(diagnosis_inputs, tmp_path):
    d, receipt, digest = diagnosis_inputs
    diagnosis_path, input_path, output = (
        tmp_path / name for name in ("diagnosis.json", "inputs.json", "frozen.json")
    )
    diagnosis_path.write_bytes(canonical_json_bytes(d))
    input_path.write_bytes(canonical_json_bytes(receipt))
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == digest
    cmd = [
        sys.executable,
        "-m",
        MODULE,
        "freeze",
        "--input",
        str(diagnosis_path),
        "--receipt",
        str(input_path),
        "--sha256",
        d["sha256"],
        "--output",
        str(output),
    ]
    before = datetime.now(UTC)
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    after = datetime.now(UTC)
    assert completed.returncode == 0, completed.stderr
    frozen = json.loads(output.read_text())
    assert before <= datetime.fromisoformat(frozen["frozen_at"]) <= after
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode != 0
    assert json.loads(output.read_text()) == frozen
    assert (
        subprocess.run(
            cmd + ["--as-of", NOW.isoformat()], capture_output=True, timeout=30
        ).returncode
        != 0
    )


def test_cli_predict_then_pending_score_uses_real_clock(diagnosis_inputs, tmp_path):
    from scripts.football_history_prospective import freeze_candidate

    d, receipt, digest = diagnosis_inputs
    candidate = freeze_candidate(d, receipt, expected_sha256=d["sha256"], receipt_sha256=digest)
    candidate_path, receipt_path, forecast_path, score_path = (
        tmp_path / name
        for name in ("candidate.json", "fixtures.json", "forecast.json", "score.json")
    )
    candidate_path.write_bytes(canonical_json_bytes(candidate))
    # Synthetic fixtures exist only in pytest's temporary directory, never in
    # the plan's real run evidence.
    snapshot = fixtures(captured_at=datetime.now(UTC).isoformat())
    snapshot["fixtures"][0]["kickoff_at"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    receipt_path.write_bytes(canonical_json_bytes(snapshot))
    command = [
        sys.executable,
        "-m",
        MODULE,
        "predict",
        "--input",
        str(candidate_path),
        "--receipt",
        str(receipt_path),
        "--sha256",
        candidate["sha256"],
        "--output",
        str(forecast_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    forecast = json.loads(forecast_path.read_text())
    assert forecast["summary"]["predicted"] == 1
    before = forecast_path.read_bytes()
    assert subprocess.run(command, capture_output=True, timeout=30).returncode != 0
    assert forecast_path.read_bytes() == before
    snapshot.update(captured_at=datetime.now(UTC).isoformat(), fixtures=[])
    receipt_path.write_bytes(canonical_json_bytes(snapshot))
    command = [
        sys.executable,
        "-m",
        MODULE,
        "score",
        "--input",
        str(forecast_path),
        "--receipt",
        str(receipt_path),
        "--sha256",
        forecast["sha256"],
        "--output",
        str(score_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(score_path.read_text())["evaluation_status"] == "awaiting_results"


def test_cli_removes_only_its_own_output_if_write_finishes_after_kickoff(
    diagnosis_inputs, tmp_path, monkeypatch
):
    from scripts.football_history_prospective import main

    candidate = freeze(diagnosis_inputs)
    forecast = predict(candidate)
    candidate_path, receipt_path, output = (
        tmp_path / name for name in ("candidate.json", "fixtures.json", "forecast.json")
    )
    candidate_path.write_bytes(canonical_json_bytes(candidate))
    receipt_path.write_bytes(canonical_json_bytes(fixtures()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prospective",
            "predict",
            "--input",
            str(candidate_path),
            "--receipt",
            str(receipt_path),
            "--sha256",
            candidate["sha256"],
            "--output",
            str(output),
        ],
    )
    with (
        patch(MODULE + ".predict_fixtures", return_value=forecast),
        patch(MODULE + "._clock", return_value=NOW + timedelta(days=2)),
    ):
        with pytest.raises(ValueError, match="no forecast retained"):
            main()
    assert not output.exists()
    assert candidate_path.exists() and receipt_path.exists()
