"""Canonical content identity for Maher model parameter artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

IDENTITY_KEY = "_artifact_identity"
SOURCE_PATHS = (
    "scripts/mle_trainer.py",
    "scripts/training_manifest.py",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize_json(value: Any) -> Any:
    """Return JSON-compatible values with stable, string-only object keys."""
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, bool):
                raise TypeError("boolean JSON object keys are not supported")
            if isinstance(key, str):
                normalized_key = key
            elif isinstance(key, int):
                normalized_key = str(key)
            else:
                raise TypeError("JSON object keys must be strings or integers")
            if normalized_key in normalized:
                raise ValueError(f"JSON object key collision after normalization: {normalized_key}")
            normalized[normalized_key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numeric values must be finite")
        return 0.0 if value == 0.0 else value
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode strict canonical JSON for hashing and JSONB persistence."""
    normalized = _normalize_json(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"value cannot be encoded as canonical UTF-8 JSON: {exc}") from exc


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _manifest_sha256(training_manifest: Mapping[str, Any]) -> str:
    fields = (
        "version",
        "selection_version",
        "minimum_team_matches",
        "cutoff_at",
        "training_start",
        "training_end",
        "included",
        "excluded",
    )
    if any(field not in training_manifest for field in fields):
        raise ValueError("training manifest is missing hash-covered fields")
    computed = hashlib.sha256(
        canonical_json_bytes({field: training_manifest[field] for field in fields})
    ).hexdigest()
    recorded = training_manifest.get("sha256")
    if not _is_sha256(recorded) or recorded != computed:
        raise ValueError("training manifest SHA-256 does not match content")
    return recorded


def _source_fingerprints(source_root: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for relative_path in SOURCE_PATHS:
        path = source_root / relative_path
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"source fingerprint unavailable for {relative_path}: {exc}") from exc
        fingerprints[relative_path] = hashlib.sha256(content).hexdigest()
    return fingerprints


def _default_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _metadata_digest(metadata: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in metadata.items() if key != "identity_sha256"}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def attach_artifact_identity(
    parameters: Mapping[str, Any],
    training_manifest: Mapping[str, Any],
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Normalize parameters and attach verifiable Maher artifact metadata."""
    if not isinstance(parameters, Mapping):
        raise ValueError("artifact parameters must be a mapping")
    if IDENTITY_KEY in parameters:
        raise ValueError(f"reserved parameter key is not allowed: {IDENTITY_KEY}")
    if not isinstance(training_manifest, Mapping):
        raise ValueError("training manifest is missing or invalid")
    manifest_sha256 = _manifest_sha256(training_manifest)
    selection_version = training_manifest.get("selection_version")
    if not isinstance(selection_version, str) or not selection_version:
        raise ValueError("training manifest selection version is missing")

    normalized_parameters = _normalize_json(parameters)
    parameter_bytes = canonical_json_bytes(normalized_parameters)
    root = source_root or _default_source_root()
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "kind": "model_parameters",
        "format": "application/json",
        "storage": "model_versions.parameters_json",
        "model_name": "maher_poisson",
        "model_version": "maher-poisson/v1",
        "input_version": "maher-spf-goals/v1",
        "preprocessing_version": selection_version,
        "calibration_version": None,
        "sha256": hashlib.sha256(parameter_bytes).hexdigest(),
        "size_bytes": len(parameter_bytes),
        "training_manifest_sha256": manifest_sha256,
        "source_files": _source_fingerprints(root),
    }
    metadata["identity_sha256"] = _metadata_digest(metadata)
    artifact = {**normalized_parameters, IDENTITY_KEY: metadata}
    verify_artifact_identity(
        artifact,
        expected_manifest_sha256=manifest_sha256,
        source_root=root,
    )
    return artifact


def verify_artifact_identity(
    artifact: Mapping[str, Any],
    *,
    expected_manifest_sha256: str | None = None,
    source_root: Path | None = None,
) -> None:
    """Raise ``ValueError`` unless parameters, metadata, manifest, and sources match."""
    if not isinstance(artifact, Mapping):
        raise ValueError("artifact parameters are missing or invalid")
    metadata = artifact.get(IDENTITY_KEY)
    if not isinstance(metadata, Mapping):
        raise ValueError("artifact identity metadata is missing")
    if metadata.get("schema_version") != 1:
        raise ValueError("artifact identity schema version is unsupported")
    fixed_fields = {
        "kind": "model_parameters",
        "format": "application/json",
        "storage": "model_versions.parameters_json",
        "model_name": "maher_poisson",
        "model_version": "maher-poisson/v1",
        "input_version": "maher-spf-goals/v1",
    }
    if any(metadata.get(field) != expected for field, expected in fixed_fields.items()):
        raise ValueError("artifact identity contract metadata is invalid")

    manifest_sha256 = metadata.get("training_manifest_sha256")
    if not _is_sha256(manifest_sha256):
        raise ValueError("artifact training manifest SHA-256 is invalid")
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("artifact training manifest does not match expected manifest")
    if (
        not isinstance(metadata.get("preprocessing_version"), str)
        or not metadata["preprocessing_version"]
    ):
        raise ValueError("artifact preprocessing version is invalid")
    if metadata.get("calibration_version") is not None:
        raise ValueError("artifact calibration version is invalid")

    parameters = {key: value for key, value in artifact.items() if key != IDENTITY_KEY}
    parameter_bytes = canonical_json_bytes(parameters)
    actual_sha256 = hashlib.sha256(parameter_bytes).hexdigest()
    if metadata.get("sha256") != actual_sha256:
        raise ValueError("artifact parameter hash does not match content")
    if metadata.get("size_bytes") != len(parameter_bytes):
        raise ValueError("artifact parameter size does not match content")
    if metadata.get("identity_sha256") != _metadata_digest(metadata):
        raise ValueError("artifact identity metadata hash does not match content")

    recorded_sources = metadata.get("source_files")
    if not isinstance(recorded_sources, Mapping) or set(recorded_sources) != set(SOURCE_PATHS):
        raise ValueError("artifact source fingerprint list is invalid")
    if any(not _is_sha256(value) for value in recorded_sources.values()):
        raise ValueError("artifact source fingerprint is invalid")
    current_sources = _source_fingerprints(source_root or _default_source_root())
    if dict(recorded_sources) != current_sources:
        raise ValueError("artifact source fingerprint does not match current source")
