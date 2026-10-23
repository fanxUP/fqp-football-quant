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
