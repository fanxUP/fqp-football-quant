from __future__ import annotations

import hashlib

import pytest

from scripts.model_artifact_identity import attach_artifact_identity
from scripts.model_prediction_run_identity import (
    build_model_artifact_identity,
    build_run_manifest,
    canonical_json_bytes,
    content_sha256,
    fingerprint_runtime_sources,
    verify_prediction_artifact_binding,
    verify_prediction_group_output_manifest,
    verify_prediction_run_manifest,
)


def test_canonical_json_and_hash_ignore_mapping_insertion_order() -> None:
    left = {"model": "maher_poisson", "params": {"away": 0.9, "home": 1.2}}
    right = {"params": {"home": 1.2, "away": 0.9}, "model": "maher_poisson"}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert content_sha256(left) == content_sha256(right)
    assert content_sha256(left) == hashlib.sha256(canonical_json_bytes(left)).hexdigest()


def test_canonical_hash_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="finite"):
        content_sha256({"probability": float("nan")})


def test_run_manifest_is_stable_and_contains_runtime_and_input_fences(tmp_path) -> None:
    source = tmp_path / "prediction.py"
    source.write_text("run-v1", encoding="utf-8")
    kwargs = {
        "release_id": "release-42",
        "source_root": tmp_path,
        "source_paths": ("prediction.py",),
        "model_manifest": [{"model_version_id": 8, "model_name": "maher_poisson"}],
        "input_manifest": {"match_ids": [9, 4], "predict_time": "2026-10-23T10:00:00"},
    }

    first = build_run_manifest(**kwargs)
    second = build_run_manifest(**kwargs)

    assert first == second
    assert (
        first["source_fingerprint"]
        == fingerprint_runtime_sources(tmp_path, ("prediction.py",))["sha256"]
    )
    assert first["input_manifest"]["match_ids"] == [4, 9]
    assert first["sha256"] == content_sha256(
        {key: value for key, value in first.items() if key != "sha256"}
    )


def test_prediction_run_manifest_verifier_rejects_tampered_components(tmp_path) -> None:
    models = [{"model_name": "market_baseline", "model_version_id": 7}]
    inputs = {"match_ids": [10, 11], "markets": [[10, "spf"]]}
    manifest = build_run_manifest(
        release_id="release-1",
        source_root=tmp_path,
        source_paths=(),
        model_manifest=models,
        input_manifest=inputs,
    )

    verify_prediction_run_manifest(
        run_manifest=manifest,
        run_manifest_sha256=manifest["sha256"],
        model_manifest=models,
        model_manifest_sha256=content_sha256(models),
        input_manifest=inputs,
        input_manifest_sha256=content_sha256(inputs),
    )

    tampered_inputs = {**inputs, "match_ids": [10, 12]}
    with pytest.raises(ValueError, match="input manifest"):
        verify_prediction_run_manifest(
            run_manifest=manifest,
            run_manifest_sha256=manifest["sha256"],
            model_manifest=models,
            model_manifest_sha256=content_sha256(models),
            input_manifest=tampered_inputs,
            input_manifest_sha256=content_sha256(inputs),
        )


def test_prediction_artifact_identity_must_match_run_model_manifest() -> None:
    identity = {
        "model_version_id": 7,
        "model_name": "market_baseline",
        "provenance_status": "complete",
        "parameters_sha256": "a" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 2,
            "sha256": "a" * 64,
        },
    }
    verify_prediction_artifact_binding([identity], identity, model_version_id=7)

    forged = {**identity, "parameters_sha256": "b" * 64}
    with pytest.raises(ValueError, match="does not match"):
        verify_prediction_artifact_binding([identity], forged, model_version_id=7)


def test_group_manifest_verifies_the_exact_persisted_json_bytes() -> None:
    manifest = {
        "match_id": 1,
        "model_version_id": 2,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["0", "1", "3"],
        "probability_vector": {"0": 0.2, "1": 0.3, "3": 0.5},
        "prediction_outputs": [
            {"option_code": "0", "model_probability": 0.2},
            {"option_code": "1", "model_probability": 0.3},
            {"option_code": "3", "model_probability": 0.5},
        ],
    }
    persisted_bytes = b'{ "match_id": 1, "model_version_id": 2, "play_type": "spf", '
    persisted_bytes += b'"market_variant": "", "predict_time": "2026-10-23T10:00:00", '
    persisted_bytes += b'"expected_options": ["0", "1", "3"], '
    persisted_bytes += b'"probability_vector": {"0": 0.2, "1": 0.3, "3": 0.5}, '
    persisted_bytes += b'"prediction_outputs": [{"option_code": "0", "model_probability": 0.2}, '
    persisted_bytes += b'{"option_code": "1", "model_probability": 0.3}, '
    persisted_bytes += b'{"option_code": "3", "model_probability": 0.5}] }'

    verify_prediction_group_output_manifest(
        output_manifest=manifest,
        output_sha256=hashlib.sha256(persisted_bytes).hexdigest(),
        output_manifest_canonical=persisted_bytes,
        match_id=1,
        model_version_id=2,
        play_type="spf",
        market_variant="",
        predict_time="2026-10-23T10:00:00",
        expected_options=["0", "1", "3"],
        probability_vector={"0": 0.2, "1": 0.3, "3": 0.5},
    )


def test_external_artifact_identity_hashes_contents_and_rejects_escape(tmp_path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifact = root / "model.bin"
    artifact.write_bytes(b"model-v1")

    identity = build_model_artifact_identity(
        12,
        "xgboost_shadow",
        {"artifact_path": "model.bin", "training_matches": 100},
        artifact_root=root,
    )

    assert identity["provenance_status"] == "complete"
    assert identity["artifact"]["sha256"] == hashlib.sha256(b"model-v1").hexdigest()
    assert identity["artifact"]["size_bytes"] == len(b"model-v1")

    escaped = build_model_artifact_identity(
        12,
        "xgboost_shadow",
        {"artifact_path": "../outside.bin"},
        artifact_root=root,
    )
    assert escaped["provenance_status"] == "incomplete"
    assert escaped["reason"] == "artifact_path_outside_root"


def test_maher_artifact_identity_rejects_forged_digest() -> None:
    identity = build_model_artifact_identity(
        12,
        "maher_poisson",
        {"home_rates": {"1": 1.1}, "_artifact_identity": {"identity_sha256": "a" * 64}},
    )

    assert identity["provenance_status"] == "incomplete"
    assert identity["reason"] == "training_manifest_identity_invalid"


def test_maher_artifact_identity_verifies_complete_metadata() -> None:
    manifest = {
        "version": "maher-spf-goals/v1",
        "selection_version": "maher-spf-goals/v1",
        "minimum_team_matches": 5,
        "cutoff_at": "2026-10-01T00:00:00",
        "training_start": "2025-01-01",
        "training_end": "2026-09-30",
        "included": [],
        "excluded": [],
    }
    manifest["sha256"] = content_sha256(manifest)
    parameters = attach_artifact_identity({"home_rates": {"1": 1.1}}, manifest)

    identity = build_model_artifact_identity(12, "maher_poisson", parameters)

    assert identity["provenance_status"] == "complete"
    assert identity["reason"] is None


def test_external_maher_artifact_still_requires_verified_training_metadata(tmp_path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "maher.bin").write_bytes(b"maher-artifact")

    identity = build_model_artifact_identity(
        12,
        "maher_poisson",
        {"artifact_path": "maher.bin", "_artifact_identity": {"identity_sha256": "a" * 64}},
        artifact_root=root,
    )

    assert identity["provenance_status"] == "incomplete"
    assert identity["reason"] == "training_manifest_identity_invalid"
