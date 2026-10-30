"""Source labels stay namespaced; conflicting official evidence cannot be bypassed."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from unittest.mock import patch

import pytest

from scripts.football_history_research import fit_history_official_research
from scripts.football_history_source_research import (
    build_source_label_manifest,
    fit_source_score_research,
)
from scripts.model_artifact_identity import canonical_json_bytes
from tests.test_data_sources.titan007.test_history_research import history, match, official


def inputs(count=12):
    rows = [
        match(i, official_match_id=None if i % 3 == 0 else i + 1000) for i in range(1, count + 1)
    ]
    evidence = [
        official(i) if i % 3 else {key: None for key in official(i)} | {"source_match_id": i}
        for i in range(1, count + 1)
    ]
    return history(rows), evidence


def rehash(value):
    value["sha256"] = hashlib.sha256(
        canonical_json_bytes({k: v for k, v in value.items() if k != "sha256"})
    ).hexdigest()
    return value


def test_mixed_cohort_uses_only_real_namespaced_ids_and_retains_unknown_availability():
    h, rows = inputs()
    manifest = build_source_label_manifest(h, rows)
    assert manifest["summary"]["included_count"] == 12
    assert manifest["summary"]["official_corroborated"] == 8
    assert manifest["summary"]["source_only"] == 4
    assert manifest["target"] == "source_reported_full_match"
    sample = manifest["included"][2]
    assert sample["label_id"] == "titan007:match:3"
    assert sample["official_evidence"] is None
    assert sample["evidence_status"] == "source_only"
    assert sample["label_available_by"] is None
    assert sample["source_published_at"] is None
    assert "result_id" not in sample and "match_id" not in sample
    assert sample["history_batch_sha256"] == h["batch"]["content_sha256"]
    assert sample["season_reference"] == h["included"][2]["season_reference"]
    assert manifest["included"][0]["official_evidence"]["result_id"] == 2001
    assert manifest["usage"]["production_ready"] is False
    assert manifest["usage"]["point_in_time_replay_verified"] is False
    assert manifest["usage"]["spf_regulation_score_verified"] is False


def test_stable_hash_and_order_cover_labels_provenance_and_restrictions():
    h, rows = inputs()
    a = build_source_label_manifest(h, rows)
    assert a == build_source_label_manifest(h, list(reversed(rows)))
    assert a == rehash(deepcopy(a))
    changed = deepcopy(h)
    changed["included"][2]["home_goals"] = 2
    assert a["sha256"] != build_source_label_manifest(rehash(changed), rows)["sha256"]
    changed = deepcopy(h)
    changed["batch"]["content_sha256"] = "c" * 64
    assert a["sha256"] != build_source_label_manifest(rehash(changed), rows)["sha256"]
    changed = deepcopy(h)
    changed["included"][0]["away_goals"] = 9
    with pytest.raises(ValueError, match="SHA-256"):
        build_source_label_manifest(changed, rows)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"home_goals": 2}, "official_score_conflict"),
        ({"match_id": 999}, "official_identity_mismatch"),
        ({"match_status": "Scheduled"}, "official_not_settled"),
        ({"result_id": None}, "official_result_missing"),
        ({"home_team_candidate_ids": [10, 99]}, "official_identity_mismatch"),
        ({"official_publish_time": "2026-11-01T00:00:00"}, "official_label_after_review"),
    ],
)
def test_linked_labels_never_fall_back_to_source_only(changes, reason):
    result = build_source_label_manifest(history(), [official(**changes)])
    assert not result["included"]
    assert result["excluded"][0]["reason"] == reason


def test_missing_evidence_is_not_claimed_to_mean_no_official_link():
    h, rows = inputs()
    result = build_source_label_manifest(h, rows[:-1])
    assert result["excluded"] == [{"source_match_id": 12, "reason": "official_evidence_missing"}]
    rows[-1]["result_id"] = 888
    result = build_source_label_manifest(h, rows)
    assert result["excluded"][0]["reason"] == "unexpected_official_evidence"


def test_incomplete_null_join_row_is_not_accepted_as_verified_absence():
    h, rows = inputs()
    rows[-1] = {"source_match_id": 12}
    result = build_source_label_manifest(h, rows)
    assert result["excluded"] == [{"source_match_id": 12, "reason": "official_evidence_incomplete"}]


def test_all_source_only_labels_are_supported_without_an_official_id():
    h = history([match(i, official_match_id=None) for i in range(1, 13)])
    rows = [{key: None for key in official(i)} | {"source_match_id": i} for i in range(1, 13)]
    result = fit_source_score_research(h, rows)
    assert result["fit_status"] == "converged"
    assert result["summary"]["fitted_source_only"] == 12
    assert result["summary"]["official_corroborated"] == 0


@pytest.mark.parametrize("kind", ["duplicate", "extra", "invalid"])
def test_evidence_must_be_exact_bounded_source_identities(kind):
    h, rows = inputs()
    if kind == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif kind == "extra":
        rows.append(official(99))
    else:
        rows[0]["source_match_id"] = True
    with pytest.raises(ValueError):
        build_source_label_manifest(h, rows)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: h["included"][0].update(source_namespace="official"),
        lambda h: h["included"][0].update(source_match_id=True),
        lambda h: h["included"][0].update(home_team_id=20),
        lambda h: h["included"][0].update(home_goals=True),
        lambda h: h["included"][0].update(score_scope="regulation_90"),
        lambda h: h["included"][0].update(source_published_at="2026-08-01T00:00:00Z"),
        lambda h: h["included"][0].pop("season_reference"),
        lambda h: h["included"][0]["season_reference"].update(source_match_id="999"),
        lambda h: h["included"][0].update(kickoff_at="2026-11-01T00:00:00Z"),
    ],
)
def test_rehashed_invalid_contract_is_rejected(mutate):
    h, rows = inputs()
    mutate(h)
    with pytest.raises(ValueError):
        build_source_label_manifest(rehash(h), rows)


def test_final_cohort_rechecks_sparse_teams_after_label_rejection():
    h = history([match(1), match(2)], min_team_matches=2)
    result = build_source_label_manifest(h, [official(1), official(2, home_goals=9)])
    assert not result["included"]
    assert {r["reason"] for r in result["excluded"]} == {
        "official_score_conflict",
        "team_below_minimum_history",
    }


def test_real_numeric_fit_matches_existing_official_fitter_on_identical_rows():
    h = history([match(i) for i in range(1, 13)])
    rows = [official(i) for i in range(1, 13)]
    expected = fit_history_official_research(h, rows)
    result = fit_source_score_research(h, rows)
    assert result["fit_status"] == "converged"
    for key in (
        "attack",
        "defense",
        "home_advantage",
        "league_intercept",
        "nll",
        "optimizer_iterations",
    ):
        assert result["fit"][key] == expected["fit"][key]
    assert result["fit"]["n_matches"] == 12
    assert "_artifact_identity" not in result["fit"]
    assert "training_manifest" not in result["fit"]
    assert result["label_manifest"]["summary"]["official_corroborated"] == 12
    assert result["source_fingerprints"]["scripts/mle_trainer.py"]


def test_source_only_rows_really_enter_optimizer_in_manifest_order():
    h, rows = inputs()
    from scripts.mle_trainer import _nll_maher_with_gradient

    with patch(
        "scripts.football_history_source_research._nll_maher_with_gradient",
        wraps=_nll_maher_with_gradient,
    ) as objective:
        result = fit_source_score_research(h, rows)
    assert result["fit_status"] == "converged"
    assert result["fit"]["n_matches"] == 12
    assert result["summary"]["fitted_source_only"] == 4
    used_args = objective.call_args.args
    labels = result["label_manifest"]["included"]
    assert used_args[4] == [r["home_goals"] for r in labels]
    assert used_args[5] == [r["away_goals"] for r in labels]
    assert result["sha256"] == rehash(deepcopy(result))["sha256"]


def test_insufficient_data_is_unfitted_and_optimizer_failure_is_not_success():
    small = fit_source_score_research(history(), [official()])
    assert small["fit_status"] == "insufficient_data"
    assert small["summary"]["fitted_matches"] == 0
    h, rows = inputs()
    from scipy.optimize import OptimizeResult

    with patch(
        "scipy.optimize.minimize",
        return_value=OptimizeResult(
            success=False, x=[0.0] * 6, fun=0.0, message="test limit", nit=0, jac=[1.0] * 6
        ),
    ):
        failed = fit_source_score_research(h, rows)
    assert failed["fit_status"] == "not_converged"
    assert failed["summary"]["fitted_matches"] == 0


def test_nonfinite_optimizer_output_is_not_a_serializable_success():
    h, rows = inputs()
    from scipy.optimize import OptimizeResult

    with patch(
        "scipy.optimize.minimize",
        return_value=OptimizeResult(
            success=True,
            x=[float("nan")] * 6,
            fun=float("nan"),
            message="invalid",
            nit=1,
            jac=[float("nan")] * 6,
        ),
    ):
        result = fit_source_score_research(h, rows)
    assert result["fit_status"] == "not_converged"
    assert result["summary"]["fitted_matches"] == 0
    json.dumps(result, allow_nan=False)


def test_cli_is_local_file_only_and_refuses_overwrite(tmp_path):
    h, rows = inputs()
    receipt, output = tmp_path / "receipt.json", tmp_path / "fit.json"
    receipt.write_text(json.dumps({"history": h, "official_rows": rows}, default=str))
    cmd = [
        sys.executable,
        "-m",
        "scripts.football_history_source_research",
        "--input",
        str(receipt),
        "--output",
        str(output),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text())
    assert result["summary"]["fitted_source_only"] == 4
    assert result["input_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode != 0
    assert json.loads(output.read_text()) == result
    receipt.write_text(
        json.dumps({"history": history(), "official_rows": [official()]}, default=str)
    )
    cmd[-1] = str(tmp_path / "small.json")
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 2


def test_additional_team_ridge_has_correct_gradient_and_preserves_global_terms():
    import numpy as np

    from scripts.football_history_source_research import _source_ridge_objective
    from scripts.mle_trainer import _nll_maher_with_gradient

    params = np.array([0.2, -0.2, 0.1, -0.1, 0.3, 0.5])
    args = ([10, 20], [0, 1], [1, 0], [2, 0], [1, 3], 2)
    value, gradient = _source_ridge_objective(params, *args, extra_team_ridge=2)
    base, base_gradient = _nll_maher_with_gradient(params, *args)
    assert value - base == pytest.approx(2 * np.dot(params[:4], params[:4]))
    assert gradient[:4] - base_gradient[:4] == pytest.approx(4 * params[:4])
    assert gradient[-2:] == pytest.approx(base_gradient[-2:])
    numeric = []
    for i in range(6):
        direction = np.zeros(6)
        direction[i] = 1e-6
        plus, _ = _source_ridge_objective(params + direction, *args, extra_team_ridge=2)
        minus, _ = _source_ridge_objective(params - direction, *args, extra_team_ridge=2)
        numeric.append((plus - minus) / 2e-6)
    assert gradient == pytest.approx(numeric, abs=1e-6)


@pytest.mark.parametrize("strength", [True, -1, float("nan"), float("inf"), 101, "1"])
def test_extra_ridge_rejects_invalid_or_unbounded_strength(strength):
    from scripts.football_history_source_research import _fit_source_labels

    with pytest.raises(ValueError, match="ridge"):
        _fit_source_labels(build_source_label_manifest(*inputs()), extra_team_ridge=strength)


def test_zero_extra_ridge_keeps_default_fit_and_stronger_ridge_shrinks_team_norm():
    from scripts.football_history_source_research import _fit_source_labels

    manifest = build_source_label_manifest(*inputs())
    original = _fit_source_labels(manifest)
    assert original == _fit_source_labels(manifest, extra_team_ridge=0)
    shrunk = _fit_source_labels(manifest, extra_team_ridge=5)
    assert shrunk["converged"] is True
    assert shrunk["extra_team_ridge"] == 5
    assert sum(v * v for k in ("attack", "defense") for v in shrunk[k].values()) < sum(
        v * v for k in ("attack", "defense") for v in original[k].values()
    )
