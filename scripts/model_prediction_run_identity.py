"""Stable content identities for prediction runs and the models they execute."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _normalize_json(value: Any) -> Any:
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
                raise ValueError(f"duplicate canonical JSON key: {normalized_key}")
            normalized[normalized_key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON number must be finite")
        return 0.0 if value == 0.0 else value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON with stable key order and strict numeric/UTF-8 handling."""
    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def fingerprint_runtime_sources(
    source_root: Path,
    source_paths: Sequence[str],
) -> dict[str, Any]:
    """Hash the exact relative source files loaded by the prediction process."""
    root = source_root.resolve()
    files: dict[str, str] = {}
    for relative_path in sorted(set(source_paths)):
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"runtime source path escapes root: {relative_path}")
        if not path.is_file():
            raise ValueError(f"runtime source is unavailable: {relative_path}")
        files[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "sha256": content_sha256(files)}


def _stable_model_manifest(models: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_json(model) for model in models]
    return sorted(
        normalized,
        key=lambda model: (
            str(model.get("model_name", "")),
            int(model.get("model_version_id", 0)),
        ),
    )


def _stable_input_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_json(value)
    if "match_ids" in normalized:
        normalized["match_ids"] = sorted(set(normalized["match_ids"]))
    if "markets" in normalized:
        normalized["markets"] = sorted(normalized["markets"], key=lambda item: (item[0], item[1]))
    return normalized


def build_run_manifest(
    *,
    release_id: str,
    source_root: Path,
    source_paths: Sequence[str],
    model_manifest: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic run manifest; wall-clock time is intentionally absent."""
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("release_id is required")
    source_fingerprint = fingerprint_runtime_sources(source_root, source_paths)
    payload = {
        "schema_version": "fqp.model-prediction-run/v1",
        "release_id": release_id.strip(),
        "source_fingerprint": source_fingerprint["sha256"],
        "source_files": source_fingerprint["files"],
        "model_manifest": _stable_model_manifest(model_manifest),
        "input_manifest": _stable_input_manifest(input_manifest),
    }
    return {**payload, "sha256": content_sha256(payload)}


def _incomplete_identity(
    model_version_id: int,
    model_name: str,
    parameters: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "model_version_id": int(model_version_id),
        "model_name": model_name,
        "provenance_status": "incomplete",
        "parameters_sha256": content_sha256(parameters),
        "artifact": None,
        "reason": reason,
    }


def build_model_artifact_identity(
    model_version_id: int,
    model_name: str,
    parameters: Mapping[str, Any] | None,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Hash inline parameters or a confined external file without loading it."""
    if not isinstance(parameters, Mapping):
        return _incomplete_identity(model_version_id, model_name, {}, "parameters_unavailable")
    params_sha256 = content_sha256(parameters)
    artifact_path = parameters.get("artifact_path")
    if artifact_path is not None:
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_path_invalid"
            )
        if artifact_root is None:
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_root_unconfigured"
            )
        root = artifact_root.resolve()
        candidate = Path(artifact_path)
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if not candidate.is_relative_to(root):
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_path_outside_root"
            )
        if not candidate.is_file():
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_file_unavailable"
            )
        artifact_bytes = candidate.read_bytes()
        relative_path = candidate.relative_to(root).as_posix()
        artifact = {
            "kind": "external_file",
            "relative_path": relative_path,
            "format": candidate.suffix.lower().lstrip(".") or "unknown",
            "size_bytes": len(artifact_bytes),
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        }
        status = "complete"
        reason = None
    else:
        artifact = {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": len(canonical_json_bytes(parameters)),
            "sha256": params_sha256,
        }
        status = "complete"
        reason = None
    if model_name == "maher_poisson":
        maher_identity = parameters.get("_artifact_identity")
        if not isinstance(maher_identity, Mapping):
            status = "incomplete"
            reason = "training_manifest_identity_missing"
        else:
            from scripts.model_artifact_identity import verify_artifact_identity

            try:
                verify_artifact_identity(parameters)
            except TypeError, ValueError:
                status = "incomplete"
                reason = "training_manifest_identity_invalid"
    return {
        "model_version_id": int(model_version_id),
        "model_name": model_name,
        "provenance_status": status,
        "parameters_sha256": params_sha256,
        "artifact": artifact,
        "reason": reason,
    }
